from base64 import b64decode, b64encode
import time

from algosdk.encoding import decode_address
from tinyman.utils import TransactionGroup, int_to_bytes
from algosdk import transaction
from algosdk.encoding import decode_address, encode_address
from algosdk.logic import get_application_address
from algosdk.account import generate_account

from sdk.base_client import BaseClient
from sdk.constants import CURRENT_PERIOD_INDEX_KEY, PERIOD_COUNT_KEY
from sdk.utils import get_struct, get_box_costs


UserState = get_struct("UserState")


class TAlgoStakingClient(BaseClient):
    def __init__(self, algod, staking_app_id, vault_app_id, tiny_asset_id, talgo_asset_id, stalgo_asset_id, user_address, user_sk) -> None:
        self.algod = algod
        self.app_id = staking_app_id
        self.application_address = get_application_address(self.app_id)
        self.vault_app_id = vault_app_id
        self.tiny_asset_id = tiny_asset_id
        self.talgo_asset_id = talgo_asset_id
        self.stalgo_asset_id = stalgo_asset_id
        self.user_address = user_address
        self.keys = {}
        self.add_key(user_address, user_sk)
        self.current_timestamp = None

    def get_reward_period_box_name(self, index: int):
        return int_to_bytes(index)

    def set_reward_rate(self, total_reward_amount: int, end_timestamp: int):
        sp = self.get_suggested_params()

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["set_reward_rate", total_reward_amount, end_timestamp],
            )
        ]

        return self._submit(transactions)

    def apply_rate_change(self):
        sp = self.get_suggested_params()

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["apply_rate_change"],
            )
        ]

        return self._submit(transactions)

    def update_state(self, period_index=None):
        sp = self.get_suggested_params()
        current_period_index = self.get_global(CURRENT_PERIOD_INDEX_KEY)

        if period_index is None:
            period_index = current_period_index

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["update_state", period_index],
                boxes=[
                    (0, self.get_reward_period_box_name(period_index))
                ],
            )
        ]

        return self._submit(transactions)
    
    def get_user_state_box_name(self, account_address: str):
        return decode_address(account_address)

    def increase_stake(self, amount: int):
        sp = self.get_suggested_params()
        current_period_index = self.get_global(CURRENT_PERIOD_INDEX_KEY)

        user_state_box_name = self.get_user_state_box_name(self.user_address)
        new_boxes = {}
        if self.box_exists(user_state_box_name):
            new_boxes[user_state_box_name] = UserState

        transactions = [
            transaction.PaymentTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.application_address,
                amt=self.calculate_min_balance(boxes=new_boxes)
            ) if new_boxes else None,
            # TODO: add a check
            transaction.AssetTransferTxn(
                index=self.stalgo_asset_id,
                sender=self.user_address,
                receiver=self.user_address,
                sp=sp,
                amt=0
            ),
            transaction.AssetTransferTxn(
                index=self.talgo_asset_id,
                sender=self.user_address,
                receiver=self.application_address,
                sp=sp,
                amt=amount
            ),
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["increase_stake", amount],
                foreign_apps=[self.vault_app_id],
                foreign_assets=[self.stalgo_asset_id],
                boxes=[
                    (0, user_state_box_name),
                    (0, self.get_reward_period_box_name(current_period_index)),
                    (self.vault_app_id, user_state_box_name),
                ],
            )
        ]

        return self._submit(transactions, additional_fees=1)
    
    def decrease_stake(self, amount: int):
        sp = self.get_suggested_params()
        current_period_index = self.get_global(CURRENT_PERIOD_INDEX_KEY)
        user_state_box_name = self.get_user_state_box_name(self.user_address)

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["decrease_stake", amount],
                boxes=[
                    (0, user_state_box_name),
                    (0, self.get_reward_period_box_name(current_period_index))
                ],
                foreign_assets=[self.talgo_asset_id, self.stalgo_asset_id],
            )
        ]

        return self._submit(transactions, additional_fees=2)

    def claim_rewards(self):
        sp = self.get_suggested_params()
        current_period_index = self.get_global(CURRENT_PERIOD_INDEX_KEY)
        user_state_box_name = self.get_user_state_box_name(self.user_address)

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["claim_rewards"],
                foreign_assets=[self.tiny_asset_id],
                boxes=[
                    (0, user_state_box_name),
                    (0, self.get_reward_period_box_name(current_period_index))
                ],
            )
        ]

        return self._submit(transactions, additional_fees=1)
