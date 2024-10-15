from base64 import b64decode, b64encode
import time

from algosdk.encoding import decode_address
from tinyman.utils import TransactionGroup, int_to_bytes
from algosdk import transaction
from algosdk.encoding import decode_address, encode_address
from algosdk.logic import get_application_address
from algosdk.account import generate_account

from sdk.utils import get_struct, get_box_costs


RewardPeriod = get_struct("RewardPeriod")
UserState = get_struct("UserState")


class Client():
    def __init__(self, algod, staking_app_id, user_address, user_sk) -> None:
        self.algod = algod
        self.app_id = staking_app_id
        self.application_address = get_application_address(self.app_id)
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
