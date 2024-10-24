import requests
from algojig import TealishProgram
from datetime import datetime, timezone

# talgo_approval_program = TealishProgram('contracts/talgo/talgo.tl')
# talgo_clear_state_program = TealishProgram('contracts/talgo/clear_state.tl')

talgo_staking_approval_program = TealishProgram("contracts/talgo_staking/talgo_staking_approval.tl")
talgo_staking_clear_state_program = TealishProgram("contracts/talgo_staking/talgo_staking_clear_state.tl")

vault_approval_program = TealishProgram(tealish=requests.get("https://github.com/tinymanorg/tinyman-governance/blob/main/contracts/vault/vault_approval.tl?raw=True").text)
vault_clear_state_program = TealishProgram(tealish=requests.get("https://github.com/tinymanorg/tinyman-governance/blob/main/contracts/vault/vault_clear_state.tl?raw=True").text)

APP_LOCAL_INTS = 0
APP_LOCAL_BYTES = 0
APP_GLOBAL_INTS = 16
APP_GLOBAL_BYTES = 16
EXTRA_PAGES = 1

DAY = 86400
WEEK = DAY * 7

MAY_1 = int(datetime(2024, 5, 1, tzinfo=timezone.utc).timestamp())
