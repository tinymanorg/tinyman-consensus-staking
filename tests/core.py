import unittest

from algosdk.account import generate_account
from algosdk.encoding import decode_address
from algosdk.logic import get_application_address
from algojig import get_suggested_params
from algojig.ledger import JigLedger

from tinyman.utils import int_to_bytes, get_global_state
from tinyman.governance.vault.constants import MAX_LOCK_TIME

from sdk.constants import *
from sdk.talgo_staking_client import TAlgoStakingClient, UserState
from sdk.utils import TAlgoStakingAppGlobalState

from tests.constants import *
from tests.utils import JigAlgod


class TalgoStakingBaseTestCase(unittest.TestCase):
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
        self.tiny_asset_id = 1003
        self.ledger.create_asset(self.tiny_asset_id, dict(total=10**15, decimals=6, name="Tinyman", unit_name="TINY", creator=self.tiny_asset_creator_address))
        self.ledger.create_app(app_id=self.vault_app_id, approval_program=vault_approval_program, creator=self.app_creator_address, local_ints=0, local_bytes=0, global_ints=4, global_bytes=0)
        self.ledger.set_global_state(self.vault_app_id, {"tiny_asset_id": self.tiny_asset_id, "total_locked_amount": 0, "total_power_count": 0, "last_total_power_timestamp": 0})
        self.ledger.set_account_balance(get_application_address(self.vault_app_id), 300_000)
        self.ledger.boxes[self.vault_app_id] = {}

        self.talgo_asset_id = 1004
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
        self.stalgo_asset_id = 1005

        self.algod = JigAlgod(self.ledger)
        self.talgo_staking_client = TAlgoStakingClient(self.algod, self.app_id, self.vault_app_id, self.tiny_asset_id, self.talgo_asset_id, self.stalgo_asset_id, self.user_address, self.user_sk)

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
                TALGO_ASSET_ID_KEY: self.talgo_asset_id,
                TINY_ASSET_ID_KEY: self.tiny_asset_id,
                VAULT_APP_ID_KEY: self.vault_app_id,
                MANAGER_KEY: decode_address(self.manager_address),
                TINY_POWER_THRESHOLD_KEY: 500_000_000,
                TOTAL_CLAIMED_REWARD_AMOUNT_KEY: 0,
                CURRENT_REWARD_RATE_PER_TIME_KEY: 0,
                CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY: MAX_UINT64,
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
                "default_frozen": True,
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
        self.ledger.global_states[self.app_id][STALGO_ASSET_ID_KEY] = self.stalgo_asset_id

    def imitate_update_state(self, timestamp=None):
        now = int(datetime.now(tz=timezone.utc).timestamp())
        if timestamp is None:
            timestamp = now

        global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        assert(global_state.last_update_timestamp < timestamp)

        self.ledger.update_global_state(
            self.app_id,
            {
                ACCUMULATED_REWARDS_PER_UNIT: global_state.get_accumulated_rewards_per_unit(timestamp),
                LAST_UPDATE_TIMESTAMP_KEY: timestamp
            }
        )

    def set_reward_rate(self, total_reward_amount=10_000_000, start_timestamp=None, end_timestamp=None):
        if not (start_timestamp and end_timestamp):
            start_timestamp = start_timestamp or int(datetime.now(tz=timezone.utc).timestamp())
            end_timestamp = start_timestamp + WEEK

        self.imitate_update_state(start_timestamp)
        duration = int(end_timestamp - start_timestamp)
        reward_rate_per_time = int(total_reward_amount / duration)

        total_reward_amount_sum = self.ledger.global_states[self.app_id].get(TOTAL_REWARD_AMOUNT_SUM_KEY, 0)
        total_claimed_reward_amount = self.ledger.global_states[self.app_id].get(TOTAL_CLAIMED_REWARD_AMOUNT_KEY, 0)
        current_reward_rate_per_time_end_timestamp = self.ledger.global_states[self.app_id].get(CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY, MAX_UINT64)

        if start_timestamp < current_reward_rate_per_time_end_timestamp:
            current_reward_rate_per_time = self.ledger.global_states[self.app_id].get(CURRENT_REWARD_RATE_PER_TIME_KEY, 0)
            remaining_from_current_rate = current_reward_rate_per_time * (current_reward_rate_per_time_end_timestamp - start_timestamp)

            total_reward_amount_sum -= remaining_from_current_rate

        total_reward_amount_sum += total_reward_amount
        balance_needed = total_reward_amount_sum - total_claimed_reward_amount

        self.ledger.global_states[self.app_id][TOTAL_REWARD_AMOUNT_SUM_KEY] = total_reward_amount_sum
        self.ledger.global_states[self.app_id][CURRENT_REWARD_RATE_PER_TIME_KEY] = reward_rate_per_time
        self.ledger.global_states[self.app_id][CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY] = end_timestamp
        self.ledger.set_account_balance(self.application_address, balance_needed + 1, self.tiny_asset_id)

        return reward_rate_per_time, end_timestamp

    def simulate_user_voting_power(self, account_address=None, locked_amount=510_000_000, lock_start_time = None, lock_end_time=None):
        """
        For MAX_LOCK_TIME, locked_amount is equivalent to voting power. Added +10_000_000 microunits for rounding errors and keeping the power enough over a time span.
        """

        now = int(datetime.now(tz=timezone.utc).timestamp())

        lock_start_time = lock_start_time or now
        lock_end_time = lock_end_time or (lock_start_time + MAX_LOCK_TIME)
        assert(lock_start_time < lock_end_time)

        account_address = account_address or self.user_address
        account_state = int_to_bytes(locked_amount) + int_to_bytes(lock_end_time) + int_to_bytes(1) + int_to_bytes(0)

        self.ledger.set_box(self.vault_app_id, key=decode_address(account_address), value=account_state)

    def simulate_user_stake(self, account_address=None, staked_amount=100_000, timestamp=None):
        now = int(datetime.now(tz=timezone.utc).timestamp())

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])

        account_address = account_address or self.user_address
        timestamp = timestamp or now

        assert timestamp >= current_global_state.last_update_timestamp

        user_state = UserState()
        user_state.staked_amount = staked_amount
        user_state.accumulated_rewards_per_unit_at_last_update = 0
        user_state.accumulated_rewards = 0
        user_state.timestamp = timestamp

        self.ledger.set_box(self.app_id, key=decode_address(account_address), value=user_state._data)
        self.ledger.set_account_balance(self.application_address, staked_amount, self.talgo_asset_id)
        self.ledger.set_account_balance(account_address, 0, self.talgo_asset_id) 
        self.ledger.set_account_balance(account_address, staked_amount, self.stalgo_asset_id, frozen=True)

        # Global State Updates
        self.ledger.global_states[self.app_id][b"total_staked_amount"] = self.ledger.global_states[self.app_id].get(b"total_staked_amount", 0) + staked_amount
        self.ledger.global_states[self.app_id][b"total_staker_count"] = self.ledger.global_states[self.app_id].get(b"total_staker_count", 0) + 1

        last_update_timestamp = self.ledger.global_states[self.app_id].get(b"last_update_timestamp", 0)
        self.ledger.global_states[self.app_id][b"last_update_timestamp"] = timestamp if timestamp > last_update_timestamp else last_update_timestamp

    def get_new_talgo_staking_client(self, user_sk, user_address):
        return TAlgoStakingClient(self.algod, self.app_id, self.vault_app_id, self.tiny_asset_id, self.talgo_asset_id, self.stalgo_asset_id, user_address, user_sk)

    def get_new_user(self):
        user_sk, user_address = generate_account()
        self.ledger.set_account_balance(user_address, 100_000_000)

        return user_sk, user_address

    def get_new_user_client(self):
        user_sk, user_address = self.get_new_user()
        return self.get_new_talgo_staking_client(user_sk, user_address)
