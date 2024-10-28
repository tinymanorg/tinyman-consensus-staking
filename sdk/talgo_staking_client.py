from base64 import b64decode, b64encode
import time

from algosdk.encoding import decode_address
from tinyman.utils import TransactionGroup, int_to_bytes
from algosdk import transaction
from algosdk.encoding import decode_address, encode_address
from algosdk.logic import get_application_address
from algosdk.account import generate_account

from sdk.constants import CURRENT_PERIOD_INDEX_KEY, PERIOD_COUNT_KEY
from sdk.utils import get_struct, get_box_costs


RewardPeriod = get_struct("RewardPeriod")
UserState = get_struct("UserState")


class TAlgoStakingClient():
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

    def add_key(self, address, key):
        self.keys[address] = key

    def get_box(self, box_name, struct_name, app_id=None):
        app_id = app_id or self.app_id

        box_value = b64decode(self.algod.application_box_by_name(app_id, box_name)["value"])
        struct_class = get_struct(struct_name)
        struct = struct_class(box_value)

        return struct

    def box_exists(self, box_name, app_id=None):
        app_id = app_id or self.app_id
        try:
            self.algod.application_box_by_name(app_id, box_name)
            return True
        except Exception:
            return False

    def get_global(self, key, default=None, app_id=None):
        app_id = app_id or self.app_id
        global_state = {s["key"]: s["value"] for s in self.algod.application_info(app_id)["params"]["global-state"]}
        key = b64encode(key).decode()
        if key in global_state:
            value = global_state[key]
            if value["type"] == 2:
                return value["uint"]
            else:
                return b64decode(value["bytes"])
        else:
            return default

    def get_suggested_params(self):
        return self.algod.suggested_params()

    def get_current_timestamp(self):
        return self.current_timestamp or time.time()

    def _submit(self, transactions, additional_fees=0):
        transactions = self.flatten_transactions(transactions)
        fee = transactions[0].fee
        for txn in transactions:
            txn.fee = 0
        transactions[0].fee = (len(transactions) + additional_fees) * fee
        txn_group = TransactionGroup(transactions)
        for address, key in self.keys.items():
            txn_group.sign_with_private_key(address, key)
        txn_info = txn_group.submit(self.algod, wait=True)
        return txn_info

    def flatten_transactions(self, txns):
        result = []
        if isinstance(txns, transaction.Transaction):
            result = [txns]
        elif type(txns) == list:
            for txn in txns:
                result += self.flatten_transactions(txn)
        return result

    def calculate_min_balance(self, accounts=0, assets=0, boxes=None):
        cost = 0
        cost += accounts * 100_000
        cost += assets * 100_000
        cost += get_box_costs(boxes or {})
        return cost

    def get_reward_period_box_name(self, index: int):
        return int_to_bytes(index)

    def create_reward_period(self, total_reward_amount: int, start_timestamp: int, end_timestamp: int):
        sp = self.get_suggested_params()

        period_count = self.get_global(PERIOD_COUNT_KEY) or 0
        new_boxes = {}
        new_boxes[self.get_reward_period_box_name(period_count)] = RewardPeriod

        transactions = [
            transaction.PaymentTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.application_address,
                amt=self.calculate_min_balance(boxes=new_boxes)
            ),
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["create_reward_period", total_reward_amount, start_timestamp, end_timestamp],
                boxes=[
                    (0, self.get_reward_period_box_name(period_count))
                ],
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
