from base64 import b64decode
from datetime import datetime, timezone
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

from tinyman.utils import bytes_to_int, TransactionGroup, int_to_bytes

from sdk.talgo_staking_client import TAlgoStakingClient

from tests.constants import talgo_staking_approval_program, talgo_staking_clear_state_program, WEEK
from tests.core import BaseTestCase
from tests.constants import APP_LOCAL_INTS, APP_LOCAL_BYTES, APP_GLOBAL_INTS, APP_GLOBAL_BYTES, EXTRA_PAGES


class TAlgoStakingTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e16))

    def dummy_block(self, timestamp=None):
        if timestamp is None:
            timestamp = self.ledger.next_timestamp
        self.ledger.eval_transactions([], block_timestamp=timestamp)
        self.ledger.next_timestamp = timestamp + 1

    def test_create_talgo_staking_app(self):
        account_sk, account_address = generate_account()

        self.ledger.set_account_balance(account_address, 10_000_000)
        transactions = [
            transaction.ApplicationCreateTxn(
                sender=account_address,
                sp=self.sp,
                on_complete=OnComplete.NoOpOC,
                app_args=[b"create_application", self.talgo_asset_id, self.tiny_asset_id, self.vault_app_id, decode_address(self.manager_address)],
                approval_program=talgo_staking_approval_program.bytecode,
                clear_program=talgo_staking_clear_state_program.bytecode,
                global_schema=transaction.StateSchema(num_uints=APP_GLOBAL_INTS, num_byte_slices=APP_GLOBAL_BYTES),
                local_schema=transaction.StateSchema(num_uints=APP_LOCAL_INTS, num_byte_slices=APP_LOCAL_BYTES),
                extra_pages=EXTRA_PAGES,
                foreign_assets=[self.talgo_asset_id, self.tiny_asset_id],
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
                b"talgo_asset_id": self.talgo_asset_id,
                b"tiny_asset_id": self.tiny_asset_id,
                b"vault_app_id": self.vault_app_id,
                b"manager": decode_address(self.manager_address),
                b"tiny_power_threshold": 1000,
            }
        )

    def test_init_talgo_staking_app(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)

        self.sp.fee = 4000
        transactions = [
            transaction.ApplicationCallTxn(
                index=self.app_id,
                sender=self.manager_address,
                sp=self.sp,
                on_complete=OnComplete.NoOpOC,
                app_args=[b"init"],
                foreign_assets=[self.talgo_asset_id, self.tiny_asset_id]
            ),
        ]

        txn_group = TransactionGroup(transactions)
        txn_group.sign_with_private_key(self.manager_address, self.manager_sk)
        block = self.ledger.eval_transactions(txn_group.signed_transactions)
        block_txns = block[b'txns']

        init_transaction = block_txns[0]
        tiny_optin_itx = init_transaction[b"dt"][b"itx"][0]
        talgo_optin_itx = init_transaction[b"dt"][b"itx"][1]
        stalgo_create_itx = init_transaction[b"dt"][b"itx"][2]

        self.assertEqual(tiny_optin_itx[b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(talgo_optin_itx[b'txn'][b'xaid'], self.talgo_asset_id)

        stalgo_asset_id = stalgo_create_itx[b'caid']

        self.assertDictEqual(
            self.ledger.global_states[self.app_id],
            {
                b"stalgo_asset_id": stalgo_asset_id,
                b"talgo_asset_id": self.talgo_asset_id,
                b"tiny_asset_id": self.tiny_asset_id,
                b"vault_app_id": self.vault_app_id,
                b"manager": decode_address(self.manager_address),
                b"tiny_power_threshold": 1000,
            }
        )

    def test_create_reward_period(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        client_for_manager = TAlgoStakingClient(self.algod, self.app_id, self.vault_app_id, self.tiny_asset_id, self.talgo_asset_id, self.stalgo_asset_id, self.manager_address, self.manager_sk)

        start_timestamp = int(datetime(2025, 3, 24, tzinfo=timezone.utc).timestamp())
        end_timestamp = start_timestamp + WEEK
        client_for_manager.create_reward_period(1_000_000, start_timestamp, end_timestamp)

    def test_set_tiny_power_threshold(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        client_for_manager = TAlgoStakingClient(self.algod, self.app_id, self.vault_app_id, self.tiny_asset_id, self.talgo_asset_id, self.stalgo_asset_id, self.manager_address, self.manager_sk)

    def test_update_state(self):
        pass

    def test_increase_stake(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        self.create_reward_period(start_timestamp=now)

        self.simulate_user_voting_power()

        self.ledger.next_timestamp = now
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.t_algo_staking_client.increase_stake(100_000)

    def test_decrease_stake(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

    def test_claim_rewards(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()
