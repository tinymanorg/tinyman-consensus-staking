from base64 import b64decode
from datetime import datetime
import time
import uuid
from unittest.mock import ANY

from algojig import print_logs
from algojig.ledger import JigLedger
from algosdk import transaction
from algosdk.account import generate_account
from algosdk.encoding import decode_address, encode_address
from algosdk.logic import get_application_address
from algosdk.transaction import OnComplete
from algosdk.constants import ZERO_ADDRESS
from tinyman.utils import bytes_to_int, TransactionGroup, int_to_bytes

from tests.constants import talgo_approval_program, talgo_clear_state_program
from tests.core import BaseTestCase
from tests.constants import APP_LOCAL_INTS, APP_LOCAL_BYTES, APP_GLOBAL_INTS, APP_GLOBAL_BYTES, EXTRA_PAGES


MAY_1 = int(datetime(2024, 5, 1).timestamp())
DAY = 86400
WEEK = DAY * 7


class TestSetup(BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e16))

    def test_create_app(self):
        account_sk, account_address = generate_account()

        self.ledger.set_account_balance(account_address, 10_000_000)
        transactions = [
            transaction.ApplicationCreateTxn(
                sender=account_address,
                sp=self.sp,
                app_args=["create_application", decode_address(account_address)],
                on_complete=OnComplete.NoOpOC,
                approval_program=talgo_approval_program.bytecode,
                clear_program=talgo_clear_state_program.bytecode,
                global_schema=transaction.StateSchema(num_uints=APP_GLOBAL_INTS, num_byte_slices=APP_GLOBAL_BYTES),
                local_schema=transaction.StateSchema(num_uints=APP_LOCAL_INTS, num_byte_slices=APP_LOCAL_BYTES),
                extra_pages=EXTRA_PAGES
            ),
        ]

        txn_group = TransactionGroup(transactions)
        txn_group.sign_with_private_key(account_address, account_sk)
        block = self.ledger.eval_transactions(txn_group.signed_transactions)
        block_txns = block[b'txns']
        app_id = block_txns[0][b'apid']

        self.assertDictEqual(
            self.ledger.global_states[app_id],
            {
                b'manager': decode_address(account_address),
                b'node_manager_0': decode_address(ZERO_ADDRESS),
                b'node_manager_1': decode_address(ZERO_ADDRESS),
                b'node_manager_2': decode_address(ZERO_ADDRESS),
                b'node_manager_3': decode_address(ZERO_ADDRESS),
                b'node_manager_4': decode_address(ZERO_ADDRESS),
                b'fee_collector': decode_address(account_address),
                b'stake_manager': decode_address(account_address),
                b'protocol_fee': 10,
            }
        )

    def test_init(self):
        self.t_algo_client.init()

    def test_mint(self):
        self.t_algo_client.init()
        for x in range(5):
            # self.t_algo_client.mint(2_000_000)
            self.t_algo_client.mint(int(10e12))
            print_logs(self.ledger.last_block[b'txns'][2][b'dt'][b'lg'])
            print("rate", self.t_algo_client.get_global(b"rate"))
            print("minted_talgo", self.t_algo_client.get_global(b"minted_talgo"))
            print("algo_balance", self.t_algo_client.get_global(b"algo_balance"))
            print("total_rewards", self.t_algo_client.get_global(b"total_rewards"))
            print("protocol_talgo", self.t_algo_client.get_global(b"protocol_talgo"))
            print()

        for x in range(5):
            self.ledger.add(self.application_address, 1000)
            self.t_algo_client.sync()
            print("rate", self.t_algo_client.get_global(b"rate"))
            print("minted_talgo", self.t_algo_client.get_global(b"minted_talgo"))
            print("algo_balance", self.t_algo_client.get_global(b"algo_balance"))
            print("total_rewards", self.t_algo_client.get_global(b"total_rewards"))
            print("protocol_talgo", self.t_algo_client.get_global(b"protocol_talgo"))
            asset_id = self.t_algo_client.get_global(b"talgo_asset_id")
            print("user talgo", self.ledger.get_account_balance(self.t_algo_client.user_address, asset_id)[0])
            print()

        for x in range(5):
            self.t_algo_client.burn(2_000_000)
            print_logs(self.ledger.last_block[b'txns'][1][b'dt'][b'lg'])
            print(self.ledger.get_account_balance(self.t_algo_client.user_address, asset_id)[0])
            print("rate", self.t_algo_client.get_global(b"rate"))
            print("minted_talgo", self.t_algo_client.get_global(b"minted_talgo"))
            print("algo_balance", self.t_algo_client.get_global(b"algo_balance"))
            print("total_rewards", self.t_algo_client.get_global(b"total_rewards"))
            print("protocol_talgo", self.t_algo_client.get_global(b"protocol_talgo"))
            print("user talgo", self.ledger.get_account_balance(self.t_algo_client.user_address, asset_id)[0])
            print()

    def test_go_online(self):
        self.ledger.set_global_state(self.app_id, {"node_manager_1": decode_address(self.user_address)})
        self.t_algo_client.init()
        node_index = 1
        # nonsense sample values from the Algorand docs
        vote_pk = b64decode('G/lqTV6MKspW6J8wH2d8ZliZ5XZVZsruqSBJMwLwlmo=')
        selection_pk = b64decode('LrpLhvzr+QpN/bivh6IPpOaKGbGzTTB5lJtVfixmmgk=')
        state_proof_pk = b64decode('RpUpNWfZMjZ1zOOjv3MF2tjO714jsBt0GKnNsw0ihJ4HSZwci+d9zvUi3i67LwFUJgjQ5Dz4zZgHgGduElnmSA==')
        vote_first = 0
        vote_last = 100000
        vote_key_dilution = int(100000 ** 0.5)

        fee = 0
        self.t_algo_client.go_online(node_index, vote_pk, selection_pk, state_proof_pk, vote_first, vote_last, vote_key_dilution, fee)

        fee = 2_000_000
        self.t_algo_client.go_online(node_index, vote_pk, selection_pk, state_proof_pk, vote_first, vote_last, vote_key_dilution, fee)
        a = encode_address(self.t_algo_client.get_global(b"account_1"))
        print(self.ledger.get_raw_account(a))

        self.t_algo_client.go_offline(node_index)
        print(self.ledger.get_raw_account(a))

    def test_set_node_manager(self):
        self.ledger.set_global_state(self.app_id, {"manager": decode_address(self.user_address)})
        self.t_algo_client.init()
        self.t_algo_client.set_node_manager(0, self.user_address)


    def test_move_stake(self):
        self.ledger.set_global_state(self.app_id, {
            "manager": decode_address(self.user_address),
            "stake_manager": decode_address(self.user_address),
        })
        self.t_algo_client.init()
        self.t_algo_client.mint(int(10e12))
        self.t_algo_client.move_stake(0, 1, int(5e12))


    def test_claim_protocol_rewards(self):
        self.t_algo_client.init()
        self.t_algo_client.mint(1_000_000)
        self.ledger.add(self.application_address, 1_000_000)
        self.t_algo_client.sync()
        self.ledger.set_account_balance(self.app_creator_address, 0, asset_id=self.t_algo_client.get_global(b"talgo_asset_id"))
        self.t_algo_client.claim_protocol_rewards()