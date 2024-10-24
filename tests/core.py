import unittest

from algosdk.account import generate_account
from algosdk.encoding import decode_address
from algosdk.logic import get_application_address
from algojig import get_suggested_params
from algojig.ledger import JigLedger

from tinyman.utils import int_to_bytes

from sdk.talgo_staking_client import TAlgoStakingClient, RewardPeriod, UserState

from tests.constants import *
from tests.utils import JigAlgod


class BaseTestCase(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app_id = 8_000
        cls.vault_app_id = 7_000
        cls.noop_app_id = 3_000

        cls.app_creator_sk, cls.app_creator_address = generate_account()
        cls.manager_sk, cls.manager_address = generate_account()

        cls.tiny_asset_creator_sk, cls.tiny_asset_creator_address = generate_account()

        cls.user_sk, cls.user_address = ("ckFZbhsmsdIuT/jJlAG9MWGXN6sYpq1X9OKVbsGFeOYBChEy71FWSsru0yawsDx1bWtJE2UdV5nolNL6tUEzmA==", "AEFBCMXPKFLEVSXO2MTLBMB4OVWWWSITMUOVPGPISTJPVNKBGOMKU54THY")
        cls.sp = get_suggested_params()

    def setUp(self):
        self.ledger = JigLedger()
        self.ledger.set_account_balance(self.user_address, 100_000_000)
        self.ledger.set_account_balance(self.app_creator_address, 10_000_000)
        self.ledger.set_account_balance(self.manager_address, 10_000_000)
        self.ledger.set_account_balance(self.tiny_asset_creator_address, 10_000_000)

        # Set up Vault
        self.tiny_asset_id = 12345
        self.ledger.create_asset(self.tiny_asset_id, dict(total=10**15, decimals=6, name="Tinyman", unit_name="TINY", creator=self.tiny_asset_creator_address))
        self.ledger.create_app(app_id=self.vault_app_id, approval_program=vault_approval_program, creator=self.app_creator_address, local_ints=0, local_bytes=0, global_ints=4, global_bytes=0)
        self.ledger.set_global_state(self.vault_app_id, {"tiny_asset_id": self.tiny_asset_id, "total_locked_amount": 0, "total_power_count": 0, "last_total_power_timestamp": 0})
        self.ledger.set_account_balance(get_application_address(self.vault_app_id), 300_000)
        self.ledger.boxes[self.vault_app_id] = {}

        self.talgo_asset_id = 78910
        self.ledger.create_asset(self.talgo_asset_id, 
            {
                "creator": self.tiny_asset_creator_address,
                "decimals": 6,
                "default-frozen": False,
                "name": "TALGO",
                "name-b64": "VEFMR08=",
                "reserve": self.tiny_asset_creator_address,
                "total": 10000000000000000,
                "unit-name": "TALGO",
                "unit-name-b64": "VEFMR08=",
                "url": "https://tinyman.org",
                "url-b64": "aHR0cHM6Ly90aW55bWFuLm9yZw=="
            }
        )

        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.application_address = get_application_address(self.app_id)
        self.stalgo_asset_id = 1112131

        self.algod = JigAlgod(self.ledger)
        self.t_algo_staking_client = TAlgoStakingClient(self.algod, self.app_id, self.vault_app_id, self.tiny_asset_id, self.talgo_asset_id, self.stalgo_asset_id, self.user_address, self.user_sk)

    def create_talgo_staking_app(self, app_id, app_creator_address):
        self.ledger.create_app(
            app_id=app_id,
            approval_program=talgo_staking_approval_program,
            creator=app_creator_address,
            local_ints=APP_LOCAL_INTS,
            local_bytes=APP_LOCAL_BYTES,
            global_ints=APP_GLOBAL_INTS,
            global_bytes=APP_GLOBAL_BYTES
        )

        self.ledger.set_global_state(
            app_id,
            {
                b"talgo_asset_id": self.talgo_asset_id,
                b"tiny_asset_id": self.tiny_asset_id,
                b"vault_app_id": self.vault_app_id,
                b"manager": decode_address(self.manager_address),
                b"tiny_power_threshold": 1000,
            }
        )

        if app_id not in self.ledger.boxes:
            self.ledger.boxes[app_id] = {}

    def init_talgo_staking_app(self):
        self.ledger.accounts[self.application_address]['balances'][self.tiny_asset_id] = [0, False]
        self.ledger.accounts[self.application_address]['balances'][self.talgo_asset_id] = [0, False]

        self.ledger.create_asset(
            self.stalgo_asset_id,
            {
                "clawback": self.application_address,
                "creator": self.application_address,
                "decimals": 6,
                "default-frozen": True,
                "freeze": self.application_address,
                "name": "Staked tALGO",
                "name-b64": "U3Rha2VkIHRBTEdP",
                "reserve": self.application_address,
                "total": 10000000000000000,
                "unit-name": "STALGO",
                "unit-name-b64": "U1RBTEdP",
                "url": "https://tinyman.org",
                "url-b64": "aHR0cHM6Ly90aW55bWFuLm9yZw=="
            }
        )
        self.ledger.global_states[self.app_id][b"stalgo_asset_id"] = self.stalgo_asset_id

    def create_reward_period(self, total_reward_amount=10_000_000, start_timestamp=None, end_timestamp=None):
        if not (start_timestamp and end_timestamp):
            start_timestamp = start_timestamp or int(datetime(2025, 3, 25, tzinfo=timezone.utc).timestamp())
            end_timestamp = start_timestamp + WEEK

        reward_period = RewardPeriod()
        reward_period.total_reward_amount = total_reward_amount
        reward_period.start_timestamp = start_timestamp
        reward_period.end_timestamp = end_timestamp

        self.ledger.boxes[self.app_id][self.t_algo_staking_client.get_reward_period_box_name(0)] = reward_period
        self.ledger.global_states[self.app_id][b"period_count"] = 1
        self.ledger.global_states[self.app_id][b"current_period_index"] = 0

    def simulate_user_voting_power(self, account_address=None, locked_amount=1000, lock_end_time=None):
        now = int(datetime.now(tz=timezone.utc).timestamp())

        account_address = account_address or self.user_address
        lock_end_time = lock_end_time or (now + 125798400)
        account_state = int_to_bytes(locked_amount) + int_to_bytes(lock_end_time) + int_to_bytes(1) + int_to_bytes(0)

        self.ledger.set_box(self.app_id, key=decode_address(account_address), value=account_state)