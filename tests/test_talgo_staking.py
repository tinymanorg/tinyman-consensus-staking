from base64 import b64decode
from datetime import datetime, timezone
import time
import uuid
from unittest.mock import ANY

from algojig import print_logs
from algojig.exceptions import LogicEvalError
from algojig.ledger import JigLedger
from algosdk import transaction
from algosdk.account import generate_account
from algosdk.encoding import decode_address, encode_address
from algosdk.logic import get_application_address
from algosdk.transaction import OnComplete

from tinyman.utils import bytes_to_int, int_to_bytes, TransactionGroup, get_global_state

from sdk.constants import *
from sdk.talgo_staking_client import TAlgoStakingClient
from sdk.event import decode_logs
from sdk.events import restaking_events
from sdk.utils import TAlgoStakingAppGlobalState, get_accumulated_rewards

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
                TINY_POWER_THRESHOLD_KEY: 500_000_000,
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
                TINY_POWER_THRESHOLD_KEY: 500_000_000,
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
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        self.set_reward_rate(start_timestamp=now)

        self.ledger.next_timestamp = now + WEEK
        self.talgo_staking_client.update_state()
        block = self.ledger.last_block
        block_txns = block[b"txns"]

        update_state_txn = block_txns[0]

    def test_update_state_fail_passed_expiration(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        self.set_reward_rate(start_timestamp=now, end_timestamp=now + WEEK)

        self.ledger.next_timestamp = now + WEEK + 1
        with self.assertRaises(LogicEvalError) as e:
            self.talgo_staking_client.update_state()
        self.assertEqual(e.exception.source['line'], 'assert(timestamp <= current_reward_rate_per_time_end_timestamp)')

    def test_apply_rate_change_on_expiration(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        self.set_reward_rate(start_timestamp=now, end_timestamp=now + WEEK)

        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.ledger.next_timestamp = now + WEEK + 1
        self.talgo_staking_client.apply_rate_change()

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        apply_rate_change_txn = block_txns[0]

        events = decode_logs(apply_rate_change_txn[b'dt'][b'lg'], restaking_events)
        apply_rate_change_event = events[-1]
        self.assertEqual(apply_rate_change_event['current_reward_rate_per_time'], 0)

        global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(global_state.last_update_timestamp, now + WEEK)
        self.assertEqual(global_state.current_reward_rate_per_time, 0)
        self.assertEqual(global_state.last_reward_rate_per_time, old_global_state.current_reward_rate_per_time)

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
        reward_transfer_itx = claim_rewards_transaction[b"dt"][b"itx"][1]

        self.assertEqual(reward_transfer_itx[b"txn"][b"xaid"], self.tiny_asset_id)
        self.assertEqual(encode_address(reward_transfer_itx[b"txn"][b"arcv"]), self.user_address)
        self.assertTrue(reward_transfer_itx[b"txn"][b"aamt"] > 0)

        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        self.assertEqual(user_state.accumulated_rewards, 0)


class UpdateStateTests(TalgoStakingBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e16))

    def test_update_state_without_staked_amount(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now)
        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])

        self.assertEqual(old_global_state.accumulated_rewards_per_unit, 0)

        self.ledger.next_timestamp = now + WEEK
        self.talgo_staking_client.update_state()

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, 0)
        self.assertEqual(current_global_state.last_update_timestamp, now + WEEK)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        update_state_txn = block_txns[0]

        events = decode_logs(update_state_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]

        self.assertEqual(state_event['last_update_timestamp'], now + WEEK),
        self.assertEqual(state_event['current_reward_rate_per_time'], reward_rate_per_time)
        self.assertEqual(state_event['accumulated_rewards_per_unit'], 0)
        self.assertEqual(state_event['total_staked_amount'], 0)

    def test_update_state_after_increase_stake(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power()

        # Increase Stake
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(old_global_state.accumulated_rewards_per_unit, 0)
        self.assertEqual(old_global_state.last_update_timestamp, now + DAY)
        self.assertEqual(old_global_state.total_staked_amount, 100_000)
        self.assertEqual(old_global_state.total_staker_count, 1)

        # Update State
        self.ledger.next_timestamp = now + WEEK
        self.talgo_staking_client.update_state()

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.get_accumulated_rewards_per_unit(current_timestamp=now + WEEK))
        self.assertEqual(current_global_state.last_update_timestamp, now + WEEK)
        self.assertEqual(current_global_state.total_staked_amount, 100_000)
        self.assertEqual(current_global_state.total_staker_count, 1)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        update_state_txn = block_txns[0]

        events = decode_logs(update_state_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]

        self.assertEqual(state_event['last_update_timestamp'], now + WEEK),
        self.assertEqual(state_event['current_reward_rate_per_time'], reward_rate_per_time)
        self.assertEqual(state_event['accumulated_rewards_per_unit'], old_global_state.get_accumulated_rewards_per_unit(current_timestamp=now + WEEK))
        self.assertEqual(state_event['total_staked_amount'], 100_000)

    def test_update_state_after_decrease_stake(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power()

        # Increase Stake
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])

        # Decrease Stake
        self.ledger.next_timestamp = now + 3 * DAY
        self.talgo_staking_client.decrease_stake(100_000)

        # Update State
        self.ledger.next_timestamp = now + WEEK
        self.talgo_staking_client.update_state()

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.get_accumulated_rewards_per_unit(current_timestamp=now + 3 * DAY))
        self.assertEqual(current_global_state.last_update_timestamp, now + WEEK)
        self.assertEqual(current_global_state.total_staked_amount, 0)
        self.assertEqual(current_global_state.total_staker_count, 0)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        update_state_txn = block_txns[0]

        events = decode_logs(update_state_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]

        self.assertEqual(state_event['last_update_timestamp'], now + WEEK),
        self.assertEqual(state_event['current_reward_rate_per_time'], reward_rate_per_time)
        self.assertEqual(state_event['accumulated_rewards_per_unit'], old_global_state.get_accumulated_rewards_per_unit(current_timestamp=now + 3 * DAY))
        self.assertEqual(state_event['total_staked_amount'], 0)

    def test_update_state_with_pending_rate_change(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        self.set_reward_rate(start_timestamp=now, end_timestamp=now + WEEK)

        self.ledger.next_timestamp = now + WEEK + 1
        with self.assertRaises(LogicEvalError) as e:
            self.talgo_staking_client.update_state()
        self.assertEqual(e.exception.source['line'], 'assert(timestamp <= current_reward_rate_per_time_end_timestamp)')

    def test_update_state_after_rate_expiration(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + WEEK)

        self.simulate_user_voting_power()

        # Increase Stake
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(old_global_state.current_reward_rate_per_time_end_timestamp, now + WEEK)

        # Apply Rate Change - Implicit Update State
        self.ledger.next_timestamp = now + WEEK + 1
        self.talgo_staking_client.apply_rate_change()

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.current_reward_rate_per_time, 0)
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.get_accumulated_rewards_per_unit(current_timestamp=old_global_state.current_reward_rate_per_time_end_timestamp))
        self.assertEqual(current_global_state.last_update_timestamp, old_global_state.current_reward_rate_per_time_end_timestamp)
        self.assertEqual(current_global_state.total_staked_amount, 100_000)
        self.assertEqual(current_global_state.total_staker_count, 1)

        # Update State
        # Rate expired, accumulated_rewards_per_unit shouldn't change.
        old_global_state = current_global_state

        self.ledger.next_timestamp = now + 2 * WEEK
        self.talgo_staking_client.update_state()

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])

        self.assertEqual(current_global_state.current_reward_rate_per_time, 0)
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.accumulated_rewards_per_unit)
        self.assertEqual(current_global_state.last_update_timestamp, now + 2 * WEEK)
        self.assertEqual(current_global_state.total_staked_amount, 100_000)
        self.assertEqual(current_global_state.total_staker_count, 1)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        update_state_txn = block_txns[0]

        events = decode_logs(update_state_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]

        self.assertEqual(state_event['last_update_timestamp'], now + 2 * WEEK),
        self.assertEqual(state_event['current_reward_rate_per_time'], 0)  # Rate expired
        self.assertEqual(state_event['accumulated_rewards_per_unit'], old_global_state.accumulated_rewards_per_unit)
        self.assertEqual(state_event['total_staked_amount'], 100_000)

    def test_update_state_after_rate_change(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power()

        # Increase Stake
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(old_global_state.accumulated_rewards_per_unit, 0)
        self.assertEqual(old_global_state.last_update_timestamp, now + DAY)
        self.assertEqual(old_global_state.total_staked_amount, 100_000)
        self.assertEqual(old_global_state.total_staker_count, 1)

        # Manager sets new rate.
        client_for_manager = TAlgoStakingClient(self.algod, self.app_id, self.vault_app_id, self.tiny_asset_id, self.talgo_asset_id, self.stalgo_asset_id, self.manager_address, self.manager_sk)

        start_timestamp = now + 2 * DAY
        end_timestamp = start_timestamp + WEEK
        reward_rate_per_time = 1_000_000 // (end_timestamp - start_timestamp)
        self.ledger.next_timestamp = start_timestamp
        client_for_manager.set_reward_rate(1_000_000, end_timestamp)

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.current_reward_rate_per_time, reward_rate_per_time)
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.get_accumulated_rewards_per_unit(now + 2 * DAY))
        self.assertEqual(current_global_state.last_update_timestamp, now + 2 * DAY)
        self.assertEqual(current_global_state.total_staked_amount, 100_000)
        self.assertEqual(current_global_state.total_staker_count, 1)

        old_global_state = current_global_state

        # Update State
        self.ledger.next_timestamp = now + WEEK
        self.talgo_staking_client.update_state()

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.get_accumulated_rewards_per_unit(current_timestamp=now + WEEK))
        self.assertEqual(current_global_state.last_update_timestamp, now + WEEK)
        self.assertEqual(current_global_state.total_staked_amount, 100_000)
        self.assertEqual(current_global_state.total_staker_count, 1)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        update_state_txn = block_txns[0]

        events = decode_logs(update_state_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]

        self.assertEqual(state_event['last_update_timestamp'], now + WEEK),
        self.assertEqual(state_event['current_reward_rate_per_time'], reward_rate_per_time)
        self.assertEqual(state_event['accumulated_rewards_per_unit'], old_global_state.get_accumulated_rewards_per_unit(current_timestamp=now + WEEK))
        self.assertEqual(state_event['total_staked_amount'], 100_000)
    

class IncreaseStakeTests(TalgoStakingBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e16))

    def test_increase_stake_without_power(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power(locked_amount=499_000_000)

        # Increase Stake
        self.ledger.next_timestamp = now + 1
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        with self.assertRaises(LogicEvalError) as e:
            self.talgo_staking_client.increase_stake(100_000)
        self.assertEqual(e.exception.source['line'], 'assert(current_tiny_power >= app_global_get(TINY_POWER_THRESHOLD_KEY))')

    def test_first_increase_stake(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power()

        # Increase Stake
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, 0)
        self.assertEqual(current_global_state.last_update_timestamp, now + DAY)
        self.assertEqual(current_global_state.total_staked_amount, 100_000)
        self.assertEqual(current_global_state.total_staker_count, 1)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        increase_stake_txn = block_txns[3]

        events = decode_logs(increase_stake_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]
        user_state_event = events[1]
        increase_stake_event = events[2]

        self.assertEqual(increase_stake_event['amount'], 100_000)
        self.assertEqual(user_state_event['user_address'], self.user_address)
        self.assertEqual(user_state_event['staked_amount'], 100_000)
        self.assertEqual(user_state_event['accumulated_rewards_per_unit_at_last_update'], 0)
        self.assertEqual(user_state_event['accumulated_rewards'], 0)
        self.assertEqual(user_state_event['timestamp'], now + DAY)

        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        self.assertEqual(user_state.staked_amount, 100_000)
        self.assertEqual(user_state.timestamp, now + DAY)
        self.assertEqual(self.ledger.get_account_balance(self.user_address, self.stalgo_asset_id), [100_000, True])

        # Inner Transaction Checks
        inner_txns = increase_stake_txn[b'dt'][b'itx']

        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'appl')
        self.assertEqual(inner_txns[0][b'txn'][b'apid'], self.vault_app_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'apaa'][0], b'get_tiny_power_of')
        self.assertEqual(inner_txns[0][b'txn'][b'apaa'][1], decode_address(self.user_address))

        self.assertEqual(inner_txns[1][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[1][b'txn'][b'xaid'], self.stalgo_asset_id)
        self.assertEqual(inner_txns[1][b'txn'][b'snd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'asnd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[1][b'txn'][b'aamt'], 100_000)

    def test_increase_stake(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power()

        # Increase Stake for user_0
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        
        # Increase Stake for user_1
        self.ledger.next_timestamp = now + 2 * DAY
        user_1_client = self.get_new_user_client()
        self.simulate_user_voting_power(user_1_client.user_address)
        self.ledger.set_account_balance(user_1_client.user_address, 120_000, self.talgo_asset_id)
        user_1_client.increase_stake(120_000)

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.current_reward_rate_per_time, reward_rate_per_time)
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.get_accumulated_rewards_per_unit(now + 2 * DAY))
        self.assertEqual(current_global_state.last_update_timestamp, now + 2 * DAY)
        self.assertEqual(current_global_state.total_staked_amount, 220_000)
        self.assertEqual(current_global_state.total_staker_count, 2)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        increase_stake_txn = block_txns[3]

        events = decode_logs(increase_stake_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]
        user_state_event = events[1]
        increase_stake_event = events[2]

        self.assertEqual(increase_stake_event['amount'], 120_000)
        self.assertEqual(user_state_event['user_address'], user_1_client.user_address)
        self.assertEqual(user_state_event['staked_amount'], 120_000)
        self.assertEqual(user_state_event['accumulated_rewards_per_unit_at_last_update'], old_global_state.get_accumulated_rewards_per_unit(now + 2 * DAY))
        self.assertEqual(user_state_event['accumulated_rewards'], 0)
        self.assertEqual(user_state_event['timestamp'], now + 2 * DAY)

        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(user_1_client.user_address), "UserState")
        self.assertEqual(user_state.staked_amount, 120_000)
        self.assertEqual(user_state.timestamp, now + 2 * DAY)
        self.assertEqual(self.ledger.get_account_balance(user_1_client.user_address, self.stalgo_asset_id), [120_000, True])

        # Inner Transaction Checks
        inner_txns = increase_stake_txn[b'dt'][b'itx']

        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'appl')
        self.assertEqual(inner_txns[0][b'txn'][b'apid'], self.vault_app_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'apaa'][0], b'get_tiny_power_of')
        self.assertEqual(inner_txns[0][b'txn'][b'apaa'][1], decode_address(user_1_client.user_address))

        self.assertEqual(inner_txns[1][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[1][b'txn'][b'xaid'], self.stalgo_asset_id)
        self.assertEqual(inner_txns[1][b'txn'][b'snd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'asnd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'arcv'], decode_address(user_1_client.user_address))
        self.assertEqual(inner_txns[1][b'txn'][b'aamt'], 120_000)

    def test_increase_stake_increment(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power()

        # Increase Stake
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])

        # Increase Stake Increment
        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        acc_rewards_at_increment = get_accumulated_rewards(user_state, old_global_state, current_timestamp=now + 2 * DAY)

        self.ledger.next_timestamp = now + 2 * DAY
        self.ledger.set_account_balance(self.user_address, 30_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(30_000)

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.current_reward_rate_per_time, reward_rate_per_time)
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.get_accumulated_rewards_per_unit(now + 2 * DAY))
        self.assertEqual(current_global_state.last_update_timestamp, now + 2 * DAY)
        self.assertEqual(current_global_state.total_staked_amount, 130_000)
        self.assertEqual(current_global_state.total_staker_count, 1)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        increase_stake_txn = block_txns[2]

        events = decode_logs(increase_stake_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]
        user_state_event = events[1]
        increase_stake_event = events[2]

        self.assertEqual(increase_stake_event['amount'], 30_000)
        self.assertEqual(user_state_event['user_address'], self.user_address)
        self.assertEqual(user_state_event['staked_amount'], 130_000)
        self.assertEqual(user_state_event['accumulated_rewards_per_unit_at_last_update'], old_global_state.get_accumulated_rewards_per_unit(now + 2 * DAY))
        self.assertEqual(user_state_event['accumulated_rewards'], acc_rewards_at_increment)
        self.assertEqual(user_state_event['timestamp'], now + 2 * DAY)

        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        self.assertEqual(user_state.staked_amount, 130_000)
        self.assertEqual(user_state.timestamp, now + 2 * DAY)
        self.assertEqual(self.ledger.get_account_balance(self.user_address, self.stalgo_asset_id), [130_000, True])


class DecreaseStakeTests(TalgoStakingBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e16))
    
    def test_decrease_stake_without_stake(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        # Decrease Stake
        self.ledger.next_timestamp = now + 1
        with self.assertRaises(LogicEvalError) as e:
            self.talgo_staking_client.decrease_stake(1)
        self.assertEqual(e.exception.source['line'], 'box<UserState> user_state = OpenBox(Txn.Sender)')

    def test_decrease_stake_full(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power()

        # Increase Stake
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])

        # Decrease Stake
        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        acc_rewards_at_decrease = get_accumulated_rewards(user_state, old_global_state, current_timestamp=now + 2 * DAY)

        self.ledger.next_timestamp = now + 2 * DAY
        self.talgo_staking_client.decrease_stake(100_000)

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.current_reward_rate_per_time, reward_rate_per_time)
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.get_accumulated_rewards_per_unit(now + 2 * DAY))
        self.assertEqual(current_global_state.last_update_timestamp, now + 2 * DAY)
        self.assertEqual(current_global_state.total_staked_amount, 0)
        self.assertEqual(current_global_state.total_staker_count, 0)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        decrease_stake_txn = block_txns[0]

        events = decode_logs(decrease_stake_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]
        user_state_event = events[1]
        decrease_stake_event = events[2]

        self.assertEqual(decrease_stake_event['amount'], 100_000)
        self.assertEqual(user_state_event['user_address'], self.user_address)
        self.assertEqual(user_state_event['staked_amount'], 0)
        self.assertEqual(user_state_event['accumulated_rewards_per_unit_at_last_update'], old_global_state.get_accumulated_rewards_per_unit(now + 2 * DAY))
        self.assertEqual(user_state_event['accumulated_rewards'], acc_rewards_at_decrease)
        self.assertEqual(user_state_event['timestamp'], now + 2 * DAY)

        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        self.assertEqual(user_state.staked_amount, 0)
        self.assertEqual(user_state.timestamp, now + 2 * DAY)
        self.assertEqual(user_state.accumulated_rewards, acc_rewards_at_decrease)
        self.assertEqual(self.ledger.get_account_balance(self.user_address, self.talgo_asset_id), [100_000, False])
        self.assertEqual(self.ledger.get_account_balance(self.user_address, self.stalgo_asset_id), [0, True])

        # Inner Transaction Checks
        inner_txns = decrease_stake_txn[b'dt'][b'itx']

        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.stalgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'asnd'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 100_000)

        self.assertEqual(inner_txns[1][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[1][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[1][b'txn'][b'snd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[1][b'txn'][b'aamt'], 100_000)

    def test_decrease_stake_partial(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power()

        # Increase Stake
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])

        # Decrease Stake
        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        acc_rewards_at_decrease = get_accumulated_rewards(user_state, old_global_state, current_timestamp=now + 2 * DAY)

        self.ledger.next_timestamp = now + 2 * DAY
        self.talgo_staking_client.decrease_stake(30_000)

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.current_reward_rate_per_time, reward_rate_per_time)
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.get_accumulated_rewards_per_unit(now + 2 * DAY))
        self.assertEqual(current_global_state.last_update_timestamp, now + 2 * DAY)
        self.assertEqual(current_global_state.total_staked_amount, 70_000)
        self.assertEqual(current_global_state.total_staker_count, 1)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        decrease_stake_txn = block_txns[0]

        events = decode_logs(decrease_stake_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]
        user_state_event = events[1]
        decrease_stake_event = events[2]

        self.assertEqual(decrease_stake_event['amount'], 30_000)
        self.assertEqual(user_state_event['user_address'], self.user_address)
        self.assertEqual(user_state_event['staked_amount'], 70_000)
        self.assertEqual(user_state_event['accumulated_rewards_per_unit_at_last_update'], old_global_state.get_accumulated_rewards_per_unit(now + 2 * DAY))
        self.assertEqual(user_state_event['accumulated_rewards'], acc_rewards_at_decrease)
        self.assertEqual(user_state_event['timestamp'], now + 2 * DAY)

        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        self.assertEqual(user_state.staked_amount, 70_000)
        self.assertEqual(user_state.timestamp, now + 2 * DAY)
        self.assertEqual(user_state.accumulated_rewards, acc_rewards_at_decrease)
        self.assertEqual(self.ledger.get_account_balance(self.user_address, self.talgo_asset_id), [30_000, False])
        self.assertEqual(self.ledger.get_account_balance(self.user_address, self.stalgo_asset_id), [70_000, True])

        # Inner Transaction Checks
        inner_txns = decrease_stake_txn[b'dt'][b'itx']

        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.stalgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'asnd'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 30_000)

        self.assertEqual(inner_txns[1][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[1][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[1][b'txn'][b'snd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[1][b'txn'][b'aamt'], 30_000)

    def test_decrease_stake_with_multiple_stakes(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power()

        # Increase Stake
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        # Increase Stake for user_1.
        self.ledger.next_timestamp = now + 2 * DAY + 3
        user_1_client = self.get_new_user_client()
        self.simulate_user_voting_power(user_1_client.user_address)
        self.ledger.set_account_balance(user_1_client.user_address, 120_000, self.talgo_asset_id)
        user_1_client.increase_stake(120_000)

        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])

        # Decrease Stake
        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        user_0_acc_rewards = get_accumulated_rewards(user_state, old_global_state, current_timestamp=now + 3 * DAY)

        self.ledger.next_timestamp = now + 3 * DAY
        self.talgo_staking_client.decrease_stake(30_000)

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.current_reward_rate_per_time, reward_rate_per_time)
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.get_accumulated_rewards_per_unit(now + 3 * DAY))
        self.assertEqual(current_global_state.last_update_timestamp, now + 3 * DAY)
        self.assertEqual(current_global_state.total_staked_amount, 190_000)
        self.assertEqual(current_global_state.total_staker_count, 2)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        decrease_stake_txn = block_txns[0]

        events = decode_logs(decrease_stake_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]
        user_state_event = events[1]
        decrease_stake_event = events[2]

        self.assertEqual(decrease_stake_event['amount'], 30_000)
        self.assertEqual(user_state_event['user_address'], self.user_address)
        self.assertEqual(user_state_event['staked_amount'], 70_000)
        self.assertEqual(user_state_event['accumulated_rewards_per_unit_at_last_update'], old_global_state.get_accumulated_rewards_per_unit(now + 3 * DAY))
        self.assertEqual(user_state_event['accumulated_rewards'], user_0_acc_rewards)
        self.assertEqual(user_state_event['timestamp'], now + 3 * DAY)

        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        self.assertEqual(user_state.staked_amount, 70_000)
        self.assertEqual(user_state.timestamp, now + 3 * DAY)
        self.assertEqual(user_state.accumulated_rewards, user_0_acc_rewards)
        self.assertEqual(self.ledger.get_account_balance(self.user_address, self.talgo_asset_id), [30_000, False])
        self.assertEqual(self.ledger.get_account_balance(self.user_address, self.stalgo_asset_id), [70_000, True])

        # Inner Transaction Checks
        inner_txns = decrease_stake_txn[b'dt'][b'itx']

        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.stalgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'asnd'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 30_000)

        self.assertEqual(inner_txns[1][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[1][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[1][b'txn'][b'snd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[1][b'txn'][b'aamt'], 30_000)


class ClaimRewardsTests(TalgoStakingBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e16))
    
    def test_claim_rewards_without_power(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power()

        # Increase Stake
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        # Claim Rewards
        self.ledger.next_timestamp = now + DAY + 1
        self.simulate_user_voting_power(locked_amount=499_000_000)

        with self.assertRaises(LogicEvalError) as e:
            self.talgo_staking_client.claim_rewards()
        self.assertEqual(e.exception.source['line'], 'assert(current_tiny_power >= app_global_get(TINY_POWER_THRESHOLD_KEY))')

    def test_claim_rewards(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power()

        # Increase Stake
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])

        # Claim Rewards
        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        accumulated_rewards = get_accumulated_rewards(user_state, old_global_state, current_timestamp=now + DAY + 1)
        self.ledger.next_timestamp = now + DAY + 1
        self.talgo_staking_client.claim_rewards()

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.current_reward_rate_per_time, reward_rate_per_time)
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.get_accumulated_rewards_per_unit(now + DAY + 1))
        self.assertEqual(current_global_state.last_update_timestamp, now + DAY + 1)
        self.assertEqual(current_global_state.total_staked_amount, 100_000)
        self.assertEqual(current_global_state.total_staker_count, 1)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        claim_rewards_txn = block_txns[1]

        events = decode_logs(claim_rewards_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]
        user_state_event = events[1]
        claim_rewards_event = events[2]

        self.assertEqual(claim_rewards_event['amount'], accumulated_rewards)
        self.assertEqual(user_state_event['user_address'], self.user_address)
        self.assertEqual(user_state_event['staked_amount'], 100_000)
        self.assertEqual(user_state_event['accumulated_rewards_per_unit_at_last_update'], old_global_state.get_accumulated_rewards_per_unit(now + DAY + 1))
        self.assertEqual(user_state_event['accumulated_rewards'], 0)
        self.assertEqual(user_state_event['timestamp'], now + DAY + 1)

        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        self.assertEqual(user_state.staked_amount, 100_000)
        self.assertEqual(user_state.timestamp, now + DAY + 1)
        self.assertEqual(user_state.accumulated_rewards_per_unit_at_last_update, old_global_state.get_accumulated_rewards_per_unit(now + DAY + 1))
        self.assertEqual(user_state.accumulated_rewards, 0)
        self.assertEqual(self.ledger.get_account_balance(self.user_address, self.tiny_asset_id), [accumulated_rewards, False])

        # Inner Transaction Checks
        inner_txns = claim_rewards_txn[b'dt'][b'itx']

        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'appl')
        self.assertEqual(inner_txns[0][b'txn'][b'apid'], self.vault_app_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'apaa'][0], b'get_tiny_power_of')
        self.assertEqual(inner_txns[0][b'txn'][b'apaa'][1], decode_address(self.user_address))

        self.assertEqual(inner_txns[1][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[1][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[1][b'txn'][b'snd'], decode_address(self.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[1][b'txn'][b'aamt'], accumulated_rewards)

    def test_claim_rewards_without_stake(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        # Claim Rewards
        self.ledger.next_timestamp = now + DAY

        with self.assertRaises(LogicEvalError) as e:
            self.talgo_staking_client.claim_rewards()
        self.assertEqual(e.exception.source['line'], 'box<UserState> user_state = OpenBox(Txn.Sender)')
    
    def test_claim_rewards_same_block(self):
        self.create_talgo_staking_app(self.app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.application_address, 10_000_000)
        self.init_talgo_staking_app()

        now = int(datetime.now(tz=timezone.utc).timestamp())
        reward_rate_per_time, _ = self.set_reward_rate(start_timestamp=now, end_timestamp=now + 2 * WEEK)

        self.simulate_user_voting_power()

        # Increase Stake
        self.ledger.next_timestamp = now + DAY
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)
        self.talgo_staking_client.increase_stake(100_000)

        old_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])

        # Claim Rewards
        self.ledger.next_timestamp = now + DAY
        self.talgo_staking_client.claim_rewards()

        current_global_state = TAlgoStakingAppGlobalState.from_globalstate(self.ledger.global_states[self.app_id])
        self.assertEqual(current_global_state.current_reward_rate_per_time, reward_rate_per_time)
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, old_global_state.accumulated_rewards_per_unit)
        self.assertEqual(current_global_state.accumulated_rewards_per_unit, 0)
        self.assertEqual(current_global_state.last_update_timestamp, now + DAY)
        self.assertEqual(current_global_state.total_staked_amount, 100_000)
        self.assertEqual(current_global_state.total_staker_count, 1)

        block = self.ledger.last_block
        block_txns = block[b"txns"]
        claim_rewards_txn = block_txns[1]

        events = decode_logs(claim_rewards_txn[b'dt'][b'lg'], restaking_events)
        state_event = events[0]
        user_state_event = events[1]
        claim_rewards_event = events[2]

        self.assertEqual(claim_rewards_event['amount'], 0)
        self.assertEqual(user_state_event['user_address'], self.user_address)
        self.assertEqual(user_state_event['staked_amount'], 100_000)
        self.assertEqual(user_state_event['accumulated_rewards_per_unit_at_last_update'], old_global_state.accumulated_rewards_per_unit)
        self.assertEqual(user_state_event['accumulated_rewards'], 0)
        self.assertEqual(user_state_event['timestamp'], now + DAY)

        user_state = self.talgo_staking_client.get_box(self.talgo_staking_client.get_user_state_box_name(self.user_address), "UserState")
        self.assertEqual(user_state.staked_amount, 100_000)
        self.assertEqual(user_state.timestamp, now + DAY)
        self.assertEqual(user_state.accumulated_rewards_per_unit_at_last_update, old_global_state.accumulated_rewards_per_unit)
        self.assertEqual(user_state.accumulated_rewards, 0)
        self.assertEqual(self.ledger.get_account_balance(self.user_address, self.tiny_asset_id), [0, False])

        # Inner Transaction Checks
        self.assertTrue(b'itx' not in claim_rewards_txn[b'dt'].keys())
