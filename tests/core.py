import unittest

from algosdk.encoding import decode_address
from tinyman.utils import int_to_bytes

from tests.constants import *
from tests.utils import JigAlgod
from algosdk.logic import get_application_address
from algosdk.account import generate_account
from algojig import get_suggested_params
from algojig.ledger import JigLedger

from sdk.talgo_client import TAlgoClient

class BaseTestCase(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app_id = 2_000
        cls.noop_app_id = 3_000

        cls.app_creator_sk, cls.app_creator_address = generate_account()
        cls.deposit_address = generate_account()[1]

        cls.user_sk, cls.user_address = ("ckFZbhsmsdIuT/jJlAG9MWGXN6sYpq1X9OKVbsGFeOYBChEy71FWSsru0yawsDx1bWtJE2UdV5nolNL6tUEzmA==", "AEFBCMXPKFLEVSXO2MTLBMB4OVWWWSITMUOVPGPISTJPVNKBGOMKU54THY")
        cls.sp = get_suggested_params()

    def setUp(self):
        self.ledger = JigLedger()
        self.ledger.set_account_balance(self.user_address, 100_000_000)
        self.ledger.set_account_balance(self.app_creator_address, 10_000_000)

        self.application_address = get_application_address(self.app_id)
        self.create_talgo_app(self.app_id, self.app_creator_address)

        self.t_algo_client = TAlgoClient(JigAlgod(self.ledger), self.app_id, self.user_address, self.user_sk)

    def create_talgo_app(self, app_id, app_creator_address):
        self.ledger.create_app(
            app_id=app_id,
            approval_program=talgo_approval_program,
            creator=app_creator_address,
            local_ints=APP_LOCAL_INTS,
            local_bytes=APP_LOCAL_BYTES,
            global_ints=APP_GLOBAL_INTS,
            global_bytes=APP_GLOBAL_BYTES
        )

        # 100_000 for basic min balance requirement
        # self.ledger.set_account_balance(self.application_address, 100_000)
        # self.ledger.set_account_balance(self.rewards_address, 100_000)
        # self.ledger.set_auth_addr(self.rewards_address, self.application_address)  # Rekey rewards_address to app address

        self.ledger.set_global_state(
            app_id,
            {
                b"manager": decode_address(app_creator_address),
                b"node_manager_1": decode_address(app_creator_address),
                b"protocol_fee": 10,
            }
        )

        if app_id not in self.ledger.boxes:
            self.ledger.boxes[app_id] = {}
