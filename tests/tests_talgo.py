from base64 import b64decode
from datetime import datetime
import time
import unittest
import uuid
from unittest.mock import ANY

from algojig import print_logs
from algojig import get_suggested_params
from algojig.ledger import JigLedger
from algojig import TealishProgram
from algojig.exceptions import LogicEvalError
from algosdk import transaction
from algosdk.account import generate_account
from algosdk.encoding import decode_address, encode_address
from algosdk.logic import get_application_address
from algosdk.transaction import OnComplete
from algosdk.constants import ZERO_ADDRESS
from sdk.event import decode_logs
from tinyman.utils import bytes_to_int, TransactionGroup, int_to_bytes
from tests.utils import JigAlgod

from sdk.talgo_client import TAlgoClient
from sdk.events import talgo_events


APP_LOCAL_INTS = 0
APP_LOCAL_BYTES = 0
APP_GLOBAL_INTS = 16
APP_GLOBAL_BYTES = 16
EXTRA_PAGES = 1

talgo_approval_program = TealishProgram('contracts/talgo/talgo_approval.tl')
talgo_clear_state_program = TealishProgram('contracts/talgo/talgo_clear_state.tl')

RATE_SCALER = int(1e12)


class TestSetup(unittest.TestCase):

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
        super().setUp()
        self.ledger = JigLedger()
        self.ledger.set_account_balance(self.app_creator_address, 10_000_000)

        self.application_address = get_application_address(self.app_id)
        self.create_talgo_app(self.app_id, self.app_creator_address)

        self.t_algo_client = TAlgoClient(JigAlgod(self.ledger), self.app_id, self.user_address, self.user_sk)
        self.ledger.set_account_balance(self.user_address, int(1e16))

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

        self.ledger.set_global_state(
            app_id,
            {
                b"manager": decode_address(app_creator_address),
                b"node_manager_1": decode_address(app_creator_address),
                b"fee_collector": decode_address(app_creator_address),
                b"protocol_fee": 10,
                b"max_account_balance": 65_000_000_000_000,
            }
        )

        if app_id not in self.ledger.boxes:
            self.ledger.boxes[app_id] = {}

    def test_create_app(self):
        account_sk, account_address = generate_account()

        self.ledger.set_account_balance(account_address, 10_000_000)
        transactions = [
            transaction.ApplicationCreateTxn(
                sender=account_address,
                sp=self.sp,
                app_args=["create_application"],
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
                b'max_account_balance': 65_000_000_000_000,
            }
        )

    def test_init(self):
        self.t_algo_client.init()

    def test_mint_only(self):
        self.t_algo_client.init()
        talgo_asset_id = self.t_algo_client.get_global(b"talgo_asset_id")
        expected_algo_balance = 0
        expected_minted_talgo = 0
        algo_amount = int(10e12)
        expected_rate = 1 * RATE_SCALER
        expected_talgo_amount = algo_amount * RATE_SCALER / expected_rate
        expected_algo_balance += algo_amount
        expected_minted_talgo += expected_talgo_amount
        self.t_algo_client.mint(algo_amount)
        logs = self.ledger.last_block[b'txns'][2][b'dt'][b'lg']
        events = decode_logs(logs, talgo_events)
        self.assertEqual(events[0]["rate"], expected_rate)
        self.assertEqual(events[1]["user_address"], self.user_address)
        self.assertEqual(events[1]["algo_amount"], algo_amount)
        self.assertEqual(events[1]["talgo_amount"], expected_talgo_amount)
        self.assertEqual(self.t_algo_client.get_global(b"rate"), expected_rate)
        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), expected_algo_balance)
        self.assertEqual(self.t_algo_client.get_global(b"minted_talgo"), expected_minted_talgo)
        self.assertEqual(self.t_algo_client.get_global(b"total_rewards"), 0)
        self.assertEqual(self.t_algo_client.get_global(b"protocol_talgo"), 0)

        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), int(10e12))
        self.assertEqual(self.ledger.get_account_balance(self.t_algo_client.user_address, talgo_asset_id)[0], expected_talgo_amount)

    def test_mint_and_rewards(self):
        self.t_algo_client.init()
        self.ledger.update_global_state(self.app_id, {b"protocol_fee": 0})
        talgo_asset_id = self.t_algo_client.get_global(b"talgo_asset_id")
        expected_algo_balance = 0
        expected_minted_talgo = 0
        expected_user_talgo_balance = 0

        # Mint 10M Algo
        algo_amount = int(10e12)
        expected_rate = 1 * RATE_SCALER
        expected_talgo_amount = int(algo_amount * RATE_SCALER / expected_rate)
        expected_algo_balance += algo_amount
        expected_minted_talgo += expected_talgo_amount
        expected_user_talgo_balance += expected_talgo_amount
        self.t_algo_client.mint(algo_amount)

        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), algo_amount)

        # Add 1 Algo reward to account
        reward = 1_000_000
        self.ledger.add(self.application_address, reward)
        self.t_algo_client.sync()

        expected_algo_balance += reward
        expected_rate = int((expected_algo_balance * RATE_SCALER) / expected_minted_talgo)
        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), expected_algo_balance)
        self.assertAlmostEqual(self.t_algo_client.get_global(b"rate"), expected_rate, delta=0)
        self.assertEqual(self.t_algo_client.get_global(b"protocol_talgo"), 0)

        # Mint 10M Algo
        algo_amount = int(10e12)
        expected_talgo_amount = int(algo_amount * RATE_SCALER / expected_rate)
        expected_algo_balance += algo_amount
        expected_minted_talgo += expected_talgo_amount
        expected_user_talgo_balance += expected_talgo_amount
        self.t_algo_client.mint(algo_amount)

        self.assertAlmostEqual(self.t_algo_client.get_global(b"rate"), expected_rate, delta=1)
        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), expected_algo_balance)
        self.assertEqual(self.t_algo_client.get_global(b"minted_talgo"), expected_minted_talgo)

        self.assertEqual(self.ledger.get_account_balance(self.t_algo_client.user_address, talgo_asset_id)[0], expected_user_talgo_balance)

        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), int(20_000_001e6))

    def test_mint_and_rewards_with_fee(self):
        self.t_algo_client.init()
        self.ledger.update_global_state(self.app_id, {b"protocol_fee": 10})
        talgo_asset_id = self.t_algo_client.get_global(b"talgo_asset_id")
        expected_algo_balance = 0
        expected_minted_talgo = 0
        expected_user_talgo_balance = 0

        # Mint 10M Algo
        algo_amount = int(10e12)
        expected_rate = 1 * RATE_SCALER
        expected_talgo_amount = int(algo_amount * RATE_SCALER / expected_rate)
        expected_algo_balance += algo_amount
        expected_minted_talgo += expected_talgo_amount
        expected_user_talgo_balance += expected_talgo_amount
        self.t_algo_client.mint(algo_amount)

        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), algo_amount)

        # Add 1 Algo reward to account
        reward = 1_000_000
        self.ledger.add(self.application_address, reward)
        self.t_algo_client.sync()

        # Assign 100_000 for protocol fees
        # 900_000 for rewards
        # update rate (+900_000 Algo)
        # mint (100_000 Algo)

        expected_algo_balance += reward
        protocol_fee = 100_000
        expected_rate = int(((expected_algo_balance - protocol_fee) * RATE_SCALER) / expected_minted_talgo)
        expected_protocol_talgo = int(protocol_fee * RATE_SCALER / expected_rate)
        expected_minted_talgo += expected_protocol_talgo
        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), expected_algo_balance)
        self.assertAlmostEqual(self.t_algo_client.get_global(b"rate"), expected_rate, delta=0)
        self.assertEqual(self.t_algo_client.get_global(b"minted_talgo"), expected_minted_talgo)
        self.assertEqual(self.t_algo_client.get_global(b"protocol_talgo"), expected_protocol_talgo)

        # Mint 10M Algo
        algo_amount = int(10e12)
        expected_talgo_amount = int(algo_amount * RATE_SCALER / expected_rate)
        expected_algo_balance += algo_amount
        expected_minted_talgo += expected_talgo_amount
        expected_user_talgo_balance += expected_talgo_amount
        self.t_algo_client.mint(algo_amount)

        self.assertAlmostEqual(self.t_algo_client.get_global(b"rate"), expected_rate, delta=1)
        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), expected_algo_balance)
        self.assertEqual(self.t_algo_client.get_global(b"minted_talgo"), expected_minted_talgo)

        self.assertEqual(self.ledger.get_account_balance(self.t_algo_client.user_address, talgo_asset_id)[0], expected_user_talgo_balance)

        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), int(20_000_001e6))

    def test_mint_and_burn_full(self):
        self.t_algo_client.init()
        talgo_asset_id = self.t_algo_client.get_global(b"talgo_asset_id")
        expected_algo_balance = 0
        expected_minted_talgo = 0
        algo_amount = int(10e12)
        expected_rate = 1 * RATE_SCALER
        expected_talgo_amount = int(algo_amount * RATE_SCALER / expected_rate)
        expected_algo_balance += algo_amount
        expected_minted_talgo += expected_talgo_amount
        self.t_algo_client.mint(algo_amount)
        self.t_algo_client.burn(expected_talgo_amount)
        logs = self.ledger.last_block[b'txns'][1][b'dt'][b'lg']
        events = decode_logs(logs, talgo_events)
        self.assertEqual(events[0]["rate"], expected_rate)
        self.assertEqual(events[1]["user_address"], self.user_address)
        self.assertEqual(events[1]["algo_amount"], algo_amount)
        self.assertEqual(events[1]["talgo_amount"], expected_talgo_amount)
        self.assertEqual(self.t_algo_client.get_global(b"rate"), expected_rate)
        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), 0)
        self.assertEqual(self.t_algo_client.get_global(b"minted_talgo"), 0)
        self.assertEqual(self.t_algo_client.get_global(b"total_rewards"), 0)
        self.assertEqual(self.t_algo_client.get_global(b"protocol_talgo"), 0)

        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), int(0))
        self.assertEqual(self.ledger.get_account_balance(self.t_algo_client.user_address, talgo_asset_id)[0], 0)

    def test_mint_and_burn_half(self):
        self.t_algo_client.init()
        talgo_asset_id = self.t_algo_client.get_global(b"talgo_asset_id")
        expected_algo_balance = 0
        expected_minted_talgo = 0
        algo_amount = int(10e12)
        expected_rate = 1 * RATE_SCALER
        expected_talgo_amount = int(algo_amount * RATE_SCALER / expected_rate)
        expected_algo_balance += algo_amount
        expected_minted_talgo += expected_talgo_amount
        self.t_algo_client.mint(algo_amount)

        half_talgo_amount = int(expected_talgo_amount / 2)
        half_algo_amount = int(algo_amount / 2)


        self.t_algo_client.burn(half_talgo_amount)
        logs = self.ledger.last_block[b'txns'][1][b'dt'][b'lg']
        events = decode_logs(logs, talgo_events)
        self.assertEqual(events[0]["rate"], expected_rate)
        self.assertEqual(events[1]["user_address"], self.user_address)
        self.assertEqual(events[1]["algo_amount"], half_algo_amount)
        self.assertEqual(events[1]["talgo_amount"], half_talgo_amount)
        self.assertEqual(self.t_algo_client.get_global(b"rate"), expected_rate)
        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), half_algo_amount)
        self.assertEqual(self.t_algo_client.get_global(b"minted_talgo"), half_talgo_amount)
        self.assertEqual(self.t_algo_client.get_global(b"total_rewards"), 0)
        self.assertEqual(self.t_algo_client.get_global(b"protocol_talgo"), 0)

        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), int(half_algo_amount))
        self.assertEqual(self.ledger.get_account_balance(self.t_algo_client.user_address, talgo_asset_id)[0], half_talgo_amount)


    def test_mint_and_donations(self):
        self.t_algo_client.init()
        self.ledger.update_global_state(self.app_id, {b"protocol_fee": 0})
        talgo_asset_id = self.t_algo_client.get_global(b"talgo_asset_id")
        expected_algo_balance = 0
        expected_minted_talgo = 0
        expected_user_talgo_balance = 0

        # Mint 10M Algo
        algo_amount = int(10e12)
        expected_rate = 1 * RATE_SCALER
        expected_talgo_amount = int(algo_amount * RATE_SCALER / expected_rate)
        expected_algo_balance += algo_amount
        expected_minted_talgo += expected_talgo_amount
        expected_user_talgo_balance += expected_talgo_amount
        self.t_algo_client.mint(algo_amount)

        self.assertEqual(self.t_algo_client.get_global(b"minted_talgo"), expected_minted_talgo)
        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), algo_amount)

        # Add 10 Algo donation/reward to account
        algo_donation = 10_000_000
        self.ledger.add(self.application_address, algo_donation)
        self.t_algo_client.sync()

        expected_algo_balance += algo_donation
        expected_rate = int((expected_algo_balance * RATE_SCALER) / expected_minted_talgo)
        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), expected_algo_balance)
        self.assertEqual(self.t_algo_client.get_global(b"rate"), expected_rate)

        # Add 10 tAlgo donation to account
        talgo_donation = 10_000_000
        self.ledger.move(talgo_donation, talgo_asset_id, self.user_address, self.application_address)
        self.t_algo_client.sync()

        expected_minted_talgo -= talgo_donation
        self.assertEqual(self.t_algo_client.get_global(b"minted_talgo"), expected_minted_talgo)
        expected_rate = int((expected_algo_balance * RATE_SCALER) / expected_minted_talgo)
        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), expected_algo_balance)
        self.assertEqual(self.t_algo_client.get_global(b"rate"), expected_rate)

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
        # print(self.ledger.get_raw_account(a))

        self.t_algo_client.go_offline(node_index)
        # print(self.ledger.get_raw_account(a))

    def test_go_offline_fail(self):
        address_a = generate_account()[1]
        self.ledger.set_global_state(self.app_id, {"node_manager_1": decode_address(address_a)})
        self.t_algo_client.init()
        node_index = 1
        with self.assertRaises(LogicEvalError) as e:
            self.t_algo_client.go_offline(node_index)
        self.assertEqual(e.exception.source["line"], 'assert(user_address == app_global_get(concat("node_manager_", ascii_digit(node_index))))')

    def test_move_stake(self):
        self.ledger.update_global_state(self.app_id, {
            "manager": decode_address(self.user_address),
            "stake_manager": decode_address(self.user_address),
        })
        self.t_algo_client.init()
        amount = int(10e12)
        half_amount = int(5e12)
        account_0_min_balance = 200_000
        account_1_min_balance = 100_000
        self.t_algo_client.mint(amount)
        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), amount)
        self.assertEqual(self.ledger.get_account_balance(encode_address(self.t_algo_client.get_global(b"account_0")), 0)[0], amount + account_0_min_balance)
        self.t_algo_client.move_stake(0, 1, half_amount)
        self.assertEqual(self.t_algo_client.get_global(b"algo_balance"), amount)
        self.assertEqual(self.ledger.get_account_balance(encode_address(self.t_algo_client.get_global(b"account_0")), 0)[0], half_amount + account_0_min_balance)
        self.assertEqual(self.ledger.get_account_balance(encode_address(self.t_algo_client.get_global(b"account_1")), 0)[0], half_amount + account_1_min_balance)

    def test_claim_protocol_rewards(self):
        self.t_algo_client.init()
        self.t_algo_client.mint(100_000_000)
        self.ledger.add(self.application_address, 1_000_000)
        self.t_algo_client.sync()
        self.assertEqual(self.t_algo_client.get_global(b"protocol_talgo"), 99108)
        self.ledger.set_account_balance(self.app_creator_address, 0, asset_id=self.t_algo_client.get_global(b"talgo_asset_id"))
        self.t_algo_client.claim_protocol_rewards()
        self.assertEqual(self.t_algo_client.get_global(b"protocol_talgo"), 0)

    def test_set_stake_manager(self):
        self.ledger.update_global_state(self.app_id, {"manager": decode_address(self.user_address)})
        address = generate_account()[1]
        self.t_algo_client.init()
        self.t_algo_client.set_stake_manager(address)
        self.assertEqual(self.t_algo_client.get_global(b"stake_manager"), decode_address(address))

    def test_set_stake_manager_fail(self):
        address_a = generate_account()[1]
        self.ledger.update_global_state(self.app_id, {"manager": decode_address(address_a)})
        address = generate_account()[1]
        self.t_algo_client.init()
        with self.assertRaises(LogicEvalError) as e:
            self.t_algo_client.set_stake_manager(address)
        self.assertEqual(e.exception.source["line"], 'assert(user_address == app_global_get("manager"))')

    def test_set_node_manager(self):
        self.ledger.update_global_state(self.app_id, {"manager": decode_address(self.user_address)})
        address = generate_account()[1]
        self.t_algo_client.init()
        self.t_algo_client.set_node_manager(0, address)
        self.assertEqual(self.t_algo_client.get_global(b"node_manager_0"), decode_address(address))

    def test_set_node_manager_1(self):
        self.ledger.update_global_state(self.app_id, {"manager": decode_address(self.user_address)})
        address = generate_account()[1]
        self.t_algo_client.init()
        self.t_algo_client.set_node_manager(1, address)
        self.assertEqual(self.t_algo_client.get_global(b"node_manager_1"), decode_address(address))

    def test_set_node_manager_fail(self):
        address_a = generate_account()[1]
        self.ledger.update_global_state(self.app_id, {"manager": decode_address(address_a)})
        address = generate_account()[1]
        self.t_algo_client.init()
        with self.assertRaises(LogicEvalError) as e:
            self.t_algo_client.set_node_manager(0, address)
        self.assertEqual(e.exception.source["line"], 'assert(user_address == app_global_get("manager"))')

    def test_set_fee_collector(self):
        self.ledger.update_global_state(self.app_id, {"manager": decode_address(self.user_address)})
        address = generate_account()[1]
        self.t_algo_client.init()
        self.t_algo_client.set_fee_collector(address)
        self.assertEqual(self.t_algo_client.get_global(b"fee_collector"), decode_address(address))

    def test_set_fee_collector_fail(self):
        address_a = generate_account()[1]
        self.ledger.update_global_state(self.app_id, {"manager": decode_address(address_a)})
        address = generate_account()[1]
        self.t_algo_client.init()
        with self.assertRaises(LogicEvalError) as e:
            self.t_algo_client.set_fee_collector(address)
        self.assertEqual(e.exception.source["line"], 'assert(user_address == app_global_get("manager"))')

    def test_propose_and_accept_manager(self):
        self.ledger.update_global_state(self.app_id, {"manager": decode_address(self.user_address)})
        sk, address1 = generate_account()
        self.t_algo_client.add_key(address1, sk)
        self.ledger.set_account_balance(address1, 1_000_000)

        sk, address2 = generate_account()
        self.t_algo_client.add_key(address2, sk)
        self.ledger.set_account_balance(address2, 1_000_000)

        self.t_algo_client.init()
        self.t_algo_client.propose_manager(address1)
        self.assertEqual(self.t_algo_client.get_global(b"proposed_manager"), decode_address(address1))
        self.assertEqual(self.t_algo_client.get_global(b"manager"), decode_address(self.user_address))
        
        # Try to accept from a different address
        self.t_algo_client.user_address = address2
        with self.assertRaises(LogicEvalError) as e:
            self.t_algo_client.accept_manager()
        self.assertEqual(e.exception.source["line"], 'assert(Txn.Sender == proposed_manager)')

         # Accept from the proposed address
        self.t_algo_client.user_address = address1
        self.t_algo_client.accept_manager()
        self.assertEqual(self.t_algo_client.get_global(b"proposed_manager"), None)
        self.assertEqual(self.t_algo_client.get_global(b"manager"), decode_address(address1))

        # Try to accept again from the proposed address
        with self.assertRaises(LogicEvalError) as e:
            self.t_algo_client.accept_manager()
        self.assertEqual(e.exception.source["line"], 'assert(Txn.Sender == proposed_manager)')

    def test_set_protocol_fee(self):
        self.ledger.update_global_state(self.app_id, {"manager": decode_address(self.user_address)})
        self.t_algo_client.init()
        self.t_algo_client.set_protocol_fee(20)
        self.assertEqual(self.t_algo_client.get_global(b"protocol_fee"), 20)

    def test_set_max_account_balance(self):
        self.ledger.update_global_state(self.app_id, {"manager": decode_address(self.user_address)})
        self.t_algo_client.init()
        self.t_algo_client.set_max_account_balance(int(10e12))
        self.assertEqual(self.t_algo_client.get_global(b"max_account_balance"), int(10e12))
