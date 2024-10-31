#pragma version 10

# This is a singleton app.
# This app manages up to 5 accounts that can be brought online to participate in consensus.
# The accounts potentially earn Algo through incestivised consensus when online.
# The app issues tAlgo in exchange for Algo.
# The Algo in the accounts is collectively owned by the holders of tAlgo.
# The accounts can be brought online for a node by the node_manager account set for each account.
# The stake_manager account can move Algo between the accounts to redistribute the stake as necessary.
# The node_managers receive no reward or payment from this app.
# The protocol collects a portion of rewards as a protocol fee.


# Same total supply as Algo. In reality the nowhere near the total supply of Algo can be staked in this contract
const int TALGO_TOTAL_SUPPLY = 10_000_000_000_000_000

# The rate of Algo/tAlgo is scaled by this value for integer storage and calculation
const int RATE_SCALER = 1_000_000_000_000

# The Algorand protocol limit is 70M Algo per online account to remain eligible for proposer rewards. 
# We set 69M to allow space for rewards to accumulate.
# This means a max of 345M Algo (69M*5) can be staked with tAlgo
# TODO: this might be made configurable or dependant on a protocol field
const int MAX_ACCOUNT_BALANCE = 69_000_000_000_000

# A simple app that rekeys its account to the creator on creation. See auxapp.tl
const bytes AUX_PROGRAM = "\n1\x18\x81\x00\x12D\xb1\x81\x01\xb2\x101\x00\xb2\x071\x00\xb2 \x81\x00\xb2\x01\xb3\x81\x01C"

# This is a LogicSig that allows anything. It is used with change_online_status()
# TEAL: "#pragma version 10\npushint 1\nreturn"
# BYTES: "\n\x81\x01C"
# KEY_REG_LOGIC_SIG_ADDRESS = U3ZXEUNFRSUDPPNFC6U7OBYO4S4AUOEP4RDBI23L2Q5TX3K5LTSVWQOKFM
const bytes KEY_REG_LOGIC_SIG_ADDRESS = "\xa6\xf3rQ\xa5\x8c\xa87\xbd\xa5\x17\xa9\xf7\x07\x0e\xe4\xb8\n8\x8f\xe4F\x14kk\xd4;;\xed]\\\xe5"

router:
    create_application
    update_application
    init
    mint
    burn
    sync
    claim_protocol_rewards
    move_stake
    set_manager
    set_node_manager
    set_stake_manager
    set_fee_collector
    set_protocol_fee
    change_online_status
end


#### ---------------------------------------- Public Functions ---------------------------------------------- ####

# permission: anyone
@public(OnCompletion=CreateApplication)
func create_application(manager_address: bytes[32]):
    # Set initial values for all configurable roles and settings

    # The manager has permission to change other manager roles and set the protocol fee
    app_global_put("manager", manager_address)

    # The node manager for each account has permission to bring the account online/offline with Keyreg
    app_global_put("node_manager_0", Global.ZeroAddress)
    app_global_put("node_manager_1", Global.ZeroAddress)
    app_global_put("node_manager_2", Global.ZeroAddress)
    app_global_put("node_manager_3", Global.ZeroAddress)
    app_global_put("node_manager_4", Global.ZeroAddress)

    # The stake manager has permission to move Algo between node accounts.
    app_global_put("stake_manager", manager_address)

    # The fee collector is the account that receives the protocol rewards when claim_protocol_rewards is called.
    app_global_put("fee_collector", manager_address)

    # The percentage of rewards claimable by the protocol (Tinyman)
    app_global_put("protocol_fee", 10)
    
    # create_application(manager_address)
    log(ARC28Event("create_application(address)", manager_address))
    return
end


# TODO: This must be removed before Mainnet.
@public(OnCompletion=UpdateApplication)
func update_application():
    assert(Txn.Sender == Global.CreatorAddress)
    return
end


# permission: anyone
@public()
func init():
    # ensure init has not been called before
    assert(!app_global_get("talgo_asset_id"))

    # Save the current Algo balance so this can be subtracted from the full balance later
    app_global_put("initial_balance", balance(Global.CurrentApplicationAddress))
    
    # create talgo ASA
    inner_txn:
        TypeEnum: Acfg
        Sender: Global.CurrentApplicationAddress
        ConfigAssetUnitName: "TALGO"
        ConfigAssetName: "TALGO"
        ConfigAssetTotal: TALGO_TOTAL_SUPPLY
        ConfigAssetDecimals: 6
        ConfigAssetURL: "https://tinyman.org"
        ConfigAssetReserve: Global.CurrentApplicationAddress
        Fee: 0
    end
    int talgo_asset_id = Itxn.CreatedAssetID
    # Save the talgo asset id
    app_global_put("talgo_asset_id", talgo_asset_id)

    # Set the state variables to initial values
    app_global_put("minted_talgo", 0)
    app_global_put("algo_balance", 0)
    app_global_put("rate", 1 * RATE_SCALER)
    app_global_put("total_rewards", 0)
    app_global_put("protocol_talgo", 0)

    # Set the 5 accounts used for stake
    # The first is the application account
    app_global_put("account_0", Global.CurrentApplicationAddress)
    # create 4 auxiliary accounts
    # each account creation requires in 3 inner txns
    app_global_put("account_1", create_auxiliary_account())
    app_global_put("account_2", create_auxiliary_account())
    app_global_put("account_3", create_auxiliary_account())
    app_global_put("account_4", create_auxiliary_account())

    log(ARC28Event("init(uint64,address,address,address,address,address)", itob(talgo_asset_id), app_global_get("account_0"), app_global_get("account_1"), app_global_get("account_2"), app_global_get("account_3"), app_global_get("account_4")))
    return
end


# permission: anyone
@public()
func mint(algo_amount: int):
    assert(Gtxn[-1].Amount == algo_amount)
    assert(Gtxn[-1].Receiver == Global.CurrentApplicationAddress)
    # 0. Ensure Algo balance of account 0 is still less than the max stake allowed to be eligible for rewards (allowing for some margin)
    # If the balance is too high minting is not available until the accounts are rebalanced with move_stake (or stake is reduced)
    # We can assume the balances of accounts 1-4 are kept below the max through the manual move_stake operations 
    #  because they only gain algo through move_stake or rewards
    assert(balance(app_global_get("account_0")) < MAX_ACCOUNT_BALANCE)
    # 1. Update state to account for rewards received since the last operation
    update_rewards_and_rate(algo_amount)
    log(ARC28Event("rate_update(uint64)", itob(app_global_get("rate"))))
    # 2. Calculate the amount of tAlgo for the given Algo
    int talgo_amount = calc_talgo(algo_amount)
    # 3. Update the tracked tAlgo & Algo amounts
    app_global_put("minted_talgo", app_global_get("minted_talgo") + talgo_amount)
    app_global_put("algo_balance", app_global_get("algo_balance") + algo_amount)
    # 4. Transfer the tAlgo
    transfer_talgo(Txn.Sender, talgo_amount)
    log(ARC28Event("mint(address,uint64,uint64)", Txn.Sender, itob(algo_amount), itob(talgo_amount)))
    return
end


# permission: anyone
@public()
func burn(talgo_amount: int):
    assert(Gtxn[-1].AssetAmount == talgo_amount)
    assert(Gtxn[-1].AssetReceiver == Global.CurrentApplicationAddress)
    assert(Gtxn[-1].XferAsset == app_global_get("talgo_asset_id"))
    # 1. Update state to account for rewards received since the last operation
    update_rewards_and_rate(0)
    log(ARC28Event("rate_update(uint64)", itob(app_global_get("rate"))))
    # 2. Calculate the amount of Algo for the given tAlgo
    int algo_amount = calc_algo(talgo_amount)
    # 3. Update the tracked tAlgo & Algo amounts
    app_global_put("minted_talgo", app_global_get("minted_talgo") - talgo_amount)
    app_global_put("algo_balance", app_global_get("algo_balance") - algo_amount)
    # 4. Transfer the Algo
    transfer_algo(Txn.Sender, algo_amount)
    log(ARC28Event("burn(address,uint64,uint64)", Txn.Sender, itob(talgo_amount), itob(algo_amount)))
    return
end


# permission: anyone
@public()
func claim_protocol_rewards():
    transfer_talgo(UncheckedCast(app_global_get("fee_collector"), bytes[32]), app_global_get("protocol_talgo"))
    log(ARC28Event("claim_protocol_rewards(uint64)", itob(app_global_get("protocol_talgo"))))
    return
end


# This function updates application state to account for any recently received rewards.
# These updates will happen in mint/burn in any case so calling this function is not required.
# It may be useful to sync the state if no mint/burn has happened for some time.
# It can also be useful for calling with Algod Simulate to retrieve the current rate without offline calculations.
# permission: anyone
@public()
func sync():
    update_rewards_and_rate(0)
    log(ARC28Event("rate_update(uint64)", itob(app_global_get("rate"))))
    return
end


# permission: manager
@public()
func set_manager(new_manager: bytes[32]):
    assert(Txn.Sender == app_global_get("manager"))

    app_global_put("manager", new_manager)
    log(ARC28Event("set_manager(address)", new_manager))
    return
end


# This function sets the node manager for a specific account.
# permission: manager
@public()
func set_node_manager(node_index: int, new_node_manager: bytes[32]):
    bytes[32] user_address = Txn.Sender
    assert(user_address == app_global_get("manager"))

    bytes key = concat("node_manager_", ascii_digit(node_index))
    app_global_put(key, new_node_manager)
    log(ARC28Event("set_node_manager(uint64,address)", itob(node_index), new_node_manager))
    return
end


# permission: manager
@public()
func set_stake_manager(new_stake_manager: bytes[32]):
    bytes[32] user_address = Txn.Sender
    assert(user_address == app_global_get("manager"))

    app_global_put("stake_manager", new_stake_manager)
    log(ARC28Event("set_stake_manager(address)", new_stake_manager))
    return
end


# permission: manager
@public()
func set_fee_collector(new_fee_collector: bytes[32]):
    bytes[32] user_address = Txn.Sender
    assert(user_address == app_global_get("manager"))

    app_global_put("fee_collector", new_fee_collector)
    log(ARC28Event("set_fee_collector(address)", new_fee_collector))
    return
end


# permission: manager
@public()
func set_protocol_fee(fee_amount: int):
    bytes[32] user_address = Txn.Sender
    assert(user_address == app_global_get("manager"))

    app_global_put("protocol_fee", fee_amount)
    log(ARC28Event("set_protocol_fee(uint64)", fee_amount))
    return
end


# permission: node_manager_{i}
@public()
func change_online_status(node_index: int):
    bytes[32] user_address = Txn.Sender
    assert(user_address == app_global_get(concat("node_manager_", ascii_digit(node_index))))
    bytes account_address = app_global_get(concat("account_", ascii_digit(node_index)))

    # The next txn in the group will be signed by the logicsig
    # Ensure that it rekeys back to the application address
    # Ensure that it is a Keyreg
    # Allow any keyreg fields
    # The point of this is to allow keyreg fields in future that we do not know about at compile time.
    assert(Gtxn[+1].TypeEnum == Keyreg)
    assert(Gtxn[+1].Sender == account_address)
    assert(Gtxn[+1].RekeyTo == Global.CurrentApplicationAddress)

    # If an increased fee is set in the keyreg txn, this exact fee must be paid to the same account in the txn prior to this.
    if Gtxn[+1].Fee > 0:
        assert(Gtxn[-1].Receiver == account_address)
        assert(Gtxn[-1].Amount == Gtxn[+1].Fee)
    end
    inner_txn:
        Sender: account_address
        TypeEnum: Pay
        RekeyTo: KEY_REG_LOGIC_SIG_ADDRESS
        Fee: 0
    end
    log(ARC28Event("change_online_status(uint64)", itob(node_index)))
    return
end


# permission: stake_manager
@public()
func move_stake(from_index: int, to_index: int, amount: int):
    bytes[32] user_address = Txn.Sender
    assert(user_address == app_global_get("stake_manager"))
    assert(to_index < 5)
    inner_txn:
        TypeEnum: Pay
        Sender: app_global_get(concat("account_", ascii_digit(from_index)))
        Receiver: app_global_get(concat("account_", ascii_digit(to_index)))
        Amount: amount
        Fee: 0
    end
    log(ARC28Event("move_stake(uint64,uint64,uint64)", itob(from_index), itob(to_index), itob(amount)))
    return
end


#### ---------------------------------------- Internal Functions ---------------------------------------------- ####

# Using ascii in the global state key names is technically unnecessary but it looks nice and makes debugging easier.
# It doesn't add significantly to the opcode cost as it is used sparingly.
# NOTE: i MUST be < 10
func ascii_digit(i: int) bytes:
    return extract(7, 1, itob(i + 48))
end


func update_rewards_and_rate(delta: int):
    int minted_talgo = app_global_get("minted_talgo")
    if !minted_talgo:
        return
    end
    # delta is the additional balance transferred in this txn group that we want to ignore for now
    # we are only interested in calculating rewards/donations since the last txn 
    int algo_balance = full_balance() - delta
    int new_rewards = algo_balance - app_global_get("algo_balance")
    app_global_put("total_rewards", app_global_get("total_rewards") + new_rewards)
    app_global_put("algo_balance", algo_balance)

    # Calculate the amount of Algo owed to the protocol according to "protocol_fee"
    int protocol_rewards = (new_rewards * app_global_get("protocol_fee")) / 100

    # Update the rate to account for the new rewards
    # The new protocol fee Algo must be subtracted as it is not part of the rewards to the tAlgo holders
    # int rate = (algo_balance * RATE_SCALER) / minted_talgo
    # use wide math otherwise any algo_balance over approx 18M would cause an overflow
    int rate = btoi((itob(algo_balance - protocol_rewards) b* itob(RATE_SCALER)) b/ itob(minted_talgo))
    app_global_put("rate", rate)

    # Now convert the protocol fee Algo to tAlgo (at the new rate) as it will stay staked and earn rewards
    int protocol_talgo = app_global_get("protocol_talgo")
    int new_protocol_talgo = calc_talgo(protocol_rewards) 
    protocol_talgo = protocol_talgo + new_protocol_talgo
    app_global_put("protocol_talgo", protocol_talgo)

    minted_talgo = minted_talgo + new_protocol_talgo
    app_global_put("minted_talgo", minted_talgo)
    return
end


func calc_talgo(algo_amount: int) int:
    # int talgo_amount = (algo_amount * RATE_SCALER) / app_global_get("rate")
    int talgo_amount = btoi((itob(algo_amount) b* itob(RATE_SCALER)) b/ itob(app_global_get("rate")))
    return talgo_amount
end


func calc_algo(talgo_amount: int) int:
    # int algo_amount = (talgo_amount * app_global_get("rate")) / RATE_SCALER
    int algo_amount = btoi((itob(talgo_amount) b* itob(app_global_get("rate"))) b/ itob(RATE_SCALER))
    return algo_amount
end


func create_auxiliary_account() bytes[32]:
    # 1. create application with program that rekeys its account to current app and deletes itself
    inner_txn:
        TypeEnum: Appl
        OnCompletion: DeleteApplication
        ApprovalProgram: AUX_PROGRAM
        ClearStateProgram: "\x0A\x81\x01"
        Fee: 0
    end
    int app_id = Itxn.CreatedApplicationID

    # 2. determine app address from the app id
    bytes[32] address = UncheckedCast(sha512_256(concat("appID", itob(app_id))), bytes[32])

    # 3. fund account with mbr algo
    inner_txn:
        TypeEnum: Pay
        Receiver: address
        Amount: 100_000
        Fee: 0
    end
    return address
end

# Any public method that uses this function must have account references to accounts 1-4. 
# 4 additional accounts were chosen so only a single app call would be required for mint/burn.
func full_balance() int:
    int algo = 0
    algo = algo + balance(app_global_get("account_0"))
    algo = algo + balance(app_global_get("account_1"))
    algo = algo + balance(app_global_get("account_2"))
    algo = algo + balance(app_global_get("account_3"))
    algo = algo + balance(app_global_get("account_4"))
    algo = algo - app_global_get("initial_balance")
    return algo
end


func find_account_with_highest_balance() int:
    int b = balance(app_global_get("account_0"))
    int max = b
    int account_index = 0
    b = balance(app_global_get("account_1"))
    if b > max:
        account_index = 1
        max = b
    end
    b = balance(app_global_get("account_2"))
    if b > max:
        account_index = 2
        max = b
    end
    b = balance(app_global_get("account_3"))
    if b > max:
        account_index = 3
        max = b
    end
    b = balance(app_global_get("account_4"))
    if b > max:
        account_index = 4
        max = b
    end
    return account_index
end


func transfer_talgo(receiver: bytes[32], amount: int):
    # Sender is always the Application Account
    inner_txn:
        TypeEnum: Axfer
        AssetReceiver: receiver
        AssetAmount: amount
        XferAsset: app_global_get("talgo_asset_id")
        Fee: 0
    end
    return
end


func transfer_algo(receiver: bytes[32], amount: int):
    # Send from the account with the highest balance
    int from_index = find_account_with_highest_balance()
    inner_txn:
        TypeEnum: Pay
        Sender: app_global_get(concat("account_", ascii_digit(from_index)))
        Receiver: receiver
        Amount: amount
        Fee: 0
    end
    return
end
