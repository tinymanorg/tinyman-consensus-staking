from algojig import TealishProgram

talgo_approval_program = TealishProgram('contracts/talgo/talgo.tl')
talgo_clear_state_program = TealishProgram('contracts/talgo/clear_state.tl')

APP_LOCAL_INTS = 0
APP_LOCAL_BYTES = 0
APP_GLOBAL_INTS = 16
APP_GLOBAL_BYTES = 16
EXTRA_PAGES = 1

DAY = 86400
