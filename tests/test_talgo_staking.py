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

from tinyman.utils import bytes_to_int, int_to_bytes, TransactionGroup

from sdk.constants import *
from sdk.talgo_staking_client import TAlgoStakingClient
from sdk.event import decode_logs
from sdk.events import restaking_events

from tests.constants import talgo_staking_approval_program, talgo_staking_clear_state_program, WEEK, DAY
from tests.core import TalgoStakingBaseTestCase
from tests.constants import APP_LOCAL_INTS, APP_LOCAL_BYTES, APP_GLOBAL_INTS, APP_GLOBAL_BYTES, EXTRA_PAGES


class TAlgoStakingTests(TalgoStakingBaseTestCase):
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
                TALGO_ASSET_ID_KEY: self.talgo_asset_id,
                TINY_ASSET_ID_KEY: self.tiny_asset_id,
                VAULT_APP_ID_KEY: self.vault_app_id,
                MANAGER_KEY: decode_address(self.manager_address),
                TINY_POWER_THRESHOLD_KEY: 1000,
                CURRENT_REWARD_RATE_PER_TIME_KEY: 0,
                CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY: MAX_UINT64,
                LAST_REWARD_RATE_PER_TIME_KEY: 0
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
                STALGO_ASSET_ID_KEY: stalgo_asset_id,
                TALGO_ASSET_ID_KEY: self.talgo_asset_id,
                TINY_ASSET_ID_KEY: self.tiny_asset_id,
                VAULT_APP_ID_KEY: self.vault_app_id,
                MANAGER_KEY: decode_address(self.manager_address),
                TINY_POWER_THRESHOLD_KEY: 1000,
                CURRENT_REWARD_RATE_PER_TIME_KEY: 0,
                CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY: MAX_UINT64,
                LAST_REWARD_RATE_PER_TIME_KEY: 0
            }
        )

    def test_set_reward_rate(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        client_for_manager = TAlgoStakingClient(self.algod, self.app_id, self.vault_app_id, self.tiny_asset_id, self.talgo_asset_id, self.stalgo_asset_id, self.manager_address, self.manager_sk)

        start_timestamp = int(datetime(2025, 3, 24, tzinfo=timezone.utc).timestamp())
        end_timestamp = start_timestamp + WEEK
        client_for_manager.set_reward_rate(1_000_000, end_timestamp)

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
        self.set_reward_rate(start_timestamp=now)

        self.simulate_user_voting_power()

        self.ledger.next_timestamp = now
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        self.assertEqual(user_state.staked_amount, 100_000)
        self.assertEqual(user_state.timestamp, now)
        self.assertEqual(self.ledger.get_account_balance(self.user_address, self.stalgo_asset_id), [100_000, True])

    def test_decrease_stake(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        self.set_reward_rate(start_timestamp=now)

        self.simulate_user_voting_power()
        self.simulate_user_stake(staked_amount=100_000, timestamp=now)

        self.ledger.next_timestamp = now + WEEK
        self.talgo_staking_client.decrease_stake(100_000)

        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        self.assertEqual(user_state.staked_amount, 0)
        self.assertEqual(user_state.timestamp, now + WEEK)
        self.assertEqual(self.ledger.get_account_balance(self.user_address, self.stalgo_asset_id), [0, True])

    def test_claim_rewards(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        self.set_reward_rate(start_timestamp=now)

        self.simulate_user_voting_power()
        self.simulate_user_stake(staked_amount=100_000, timestamp=now)

        self.ledger.next_timestamp = now + DAY
        self.talgo_staking_client.claim_rewards()

        block = self.ledger.last_block
        block_txns = block[b"txns"]

        claim_rewards_transaction = block_txns[1]
        reward_transfer_itx = claim_rewards_transaction[b"dt"][b"itx"][0]

        self.assertEqual(reward_transfer_itx[b"txn"][b"xaid"], self.tiny_asset_id)
        self.assertEqual(encode_address(reward_transfer_itx[b"txn"][b"arcv"]), self.user_address)
        self.assertTrue(reward_transfer_itx[b"txn"][b"aamt"] > 0)

        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        self.assertEqual(user_state.accumulated_rewards, 0)
