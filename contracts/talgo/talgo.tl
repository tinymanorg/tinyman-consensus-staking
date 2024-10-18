#pragma version 10


# This app manages up to 5 accounts that can be brought online to participate in consensus.
# The accounts potentially earn Algo through incestivised consensus when online.
# The app issues tAlgo in exchange for Algo.
# The Algo in the accounts is collectively owned by the holders of tAlgo.
# The accounts can be brought online for a node by the node_manager account set for each account
# The stake_manager account can move Algo between the accounts to redistribute the stake as necessary.
# The node_managers receive no reward or payment from this app.


const int TALGO_TOTAL_SUPPLY = 10_000_000_000_000_000
const int RATE_SCALER = 1_000_000
# The protocol limit is 70M. We set 69M to allow space for rewards to accumulate.
const int MAX_ACCOUNT_BALANCE = 69_000_000_000_000
# A simple app that rekeys its account to the creator on creation. See auxapp.tl
const bytes AUX_PROGRAM = "\n1\x18\x81\x00\x12D\xb1\x81\x01\xb2\x101\x00\xb2\x071\x00\xb2 \x81\x00\xb2\x01\xb3\x81\x01C"

router:
    create_application
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
    go_online
    go_offline
end


#### ---------------------------------------- Public Functions ---------------------------------------------- ####


@public(OnCompletion=CreateApplication)
func create_application(manager_address: bytes[32]):
	app_global_put("manager", manager_address)
    app_global_put("node_manager_0", manager_address)
    app_global_put("node_manager_1", manager_address)
    app_global_put("node_manager_2", manager_address)
    app_global_put("node_manager_3", manager_address)
    app_global_put("node_manager_4", manager_address)
    app_global_put("stake_manager", manager_address)
    app_global_put("fee_collector", manager_address)
    app_global_put("protocol_fee", 10)
    app_global_put("fee_balance", 0)
	# create_application(manager_address)
	log(ARC28Event("create_application(address)", manager_address))
    return
end


@public()
func init():
    # ensure init has not been called before
    assert(!app_global_get("talgo_asset_id"))
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
    app_global_put("talgo_asset_id", talgo_asset_id)
    app_global_put("minted_talgo", 0)
    app_global_put("rate", 1 * RATE_SCALER)

    app_global_put("account_0", Global.CurrentApplicationAddress)

    # create 4 auxiliary accounts
    # each account creation requires in 3 inner txns
    create_auxiliary_account(1)
    create_auxiliary_account(2)
    create_auxiliary_account(3)
    create_auxiliary_account(4)

    app_global_put("algo_balance", full_balance())
    return
end


@public()
func mint(algo_amount: int):
    assert(algo_amount == Gtxn[-1].Amount)
    assert(Gtxn[-1].Receiver == Global.CurrentApplicationAddress)
    # TODO: assert that receiver is this account!
    # TODO: assert other necessary stuff!
    # 0. Ensure Algo balance of account 0 is still less than the max stake allowed to be eligible for rewards (allowing for some margin)
    # If the balance is too high minting is not available until the accounts are rebalanced with move_stake (or stake is reduced)
    # We can assume the balances of accounts 1-4 are kept below the max through the manual move_stake operations 
    #  because they only gain algo through move_stake or rewards
    assert(balance(app_global_get("account_0")) < MAX_ACCOUNT_BALANCE)
    # 1. Update state to account for rewards received since the last operation
	update_rewards_and_rate(algo_amount)
    # 2. Calculate the amount of tAlgo for the given Algo
	int talgo_amount = calc_talgo(algo_amount)
    # 3. Update the tracked tAlgo & Algo amounts
    app_global_put("minted_talgo", app_global_get("minted_talgo") + talgo_amount)
    app_global_put("algo_balance", app_global_get("algo_balance") + algo_amount)
    # 4. Transfer the tAlgo
	transfer_talgo(Txn.Sender, talgo_amount)
	return
end


@public()
func burn(talgo_amount: int):
    assert(talgo_amount == Gtxn[-1].AssetAmount)
    assert(Gtxn[-1].AssetReceiver == Global.CurrentApplicationAddress)
    assert(Gtxn[-1].XferAsset == app_global_get("talgo_asset_id"))
    # TODO: assert other necessary stuff!
    # 1. Update state to account for rewards received since the last operation
	update_rewards_and_rate(0)
    # 2. Calculate the amount of Algo for the given tAlgo
	int algo_amount = calc_algo(talgo_amount)
    # 3. Update the tracked tAlgo & Algo amounts
    app_global_put("minted_talgo", app_global_get("minted_talgo") - talgo_amount)
    app_global_put("algo_balance", app_global_get("algo_balance") - algo_amount)
    # 4. Transfer the Algo
	transfer_algo(Txn.Sender, algo_amount)
	return
end


@public()
func claim_protocol_rewards():
	transfer_talgo(UncheckedCast(app_global_get("fee_collector"), bytes[32]), app_global_get("protocol_talgo"))
    app_global_put("protocol_talgo", 0)
    return
end


@public()
func sync():
    update_rewards_and_rate(0)
    return
end


@public()
func set_manager(new_manager: bytes[32]):
    assert(Txn.Sender == app_global_get("manager"))

    app_global_put("manager", new_manager)
    log(ARC28Event("set_manager(address)", new_manager))
    return
end


@public()
func set_node_manager(node_index: int, new_node_manager: bytes[32]):
    bytes[32] user_address = Txn.Sender
    assert(user_address == app_global_get("manager"))

    bytes key = concat("node_manager_", ascii_digit(node_index))
    app_global_put(key, new_node_manager)
    log(ARC28Event("set_node_manager(int,address)", node_index, new_node_manager))
    return
end


@public()
func set_stake_manager(new_stake_manager: bytes[32]):
    bytes[32] user_address = Txn.Sender
    assert(user_address == app_global_get("manager"))

    app_global_put("stake_manager", new_stake_manager)
    log(ARC28Event("set_stake_manager(address)", new_stake_manager))
    return
end


@public()
func set_fee_collector(new_fee_collector: bytes[32]):
    bytes[32] user_address = Txn.Sender
    assert(user_address == app_global_get("manager"))

    app_global_put("fee_collector", new_fee_collector)
    log(ARC28Event("set_fee_collector(address)", new_fee_collector))
    return
end


@public()
func set_protocol_fee(fee_amount: int):
    bytes[32] user_address = Txn.Sender
    assert(user_address == app_global_get("manager"))

    app_global_put("protocol_fee", fee_amount)
    log(ARC28Event("set_protocol_fee(int)", fee_amount))
    return
end


@public()
func go_online(node_index: int, vote_pk: bytes[32], selection_pk: bytes[32], state_proof_pk: bytes[64], vote_first: int, vote_last: int, vote_key_dilution: int, fee: int):
    bytes[32] user_address = Txn.Sender
    bytes key = concat("node_manager_", ascii_digit(node_index))
    assert(user_address == app_global_get(key))
    bytes account_address = app_global_get(concat("account_", ascii_digit(node_index)))
    app_global_put("fee_balance", app_global_get("fee_balance") - fee)
    inner_txn:
        Sender: account_address
        TypeEnum: Keyreg
        VotePK: vote_pk
        SelectionPK: selection_pk
        StateProofPK: state_proof_pk
        VoteFirst: vote_first
        VoteLast: vote_last
        VoteKeyDilution: vote_key_dilution
        Fee: fee
    end
    return
end


@public()
func go_offline(node_index: int):
    bytes[32] user_address = Txn.Sender
    bytes key = concat("node_manager_", ascii_digit(node_index))
    assert(user_address == app_global_get(key))
    bytes account_address = app_global_get(concat("account_", ascii_digit(node_index)))
    inner_txn:
        Sender: account_address
        TypeEnum: Keyreg
    end
    return
end


@public()
func move_stake(from_index: int, to_index: int, amount: int):
    bytes[32] user_address = Txn.Sender
    assert(user_address == app_global_get("stake_manager"))
    inner_txn:
        TypeEnum: Pay
        Sender: app_global_get(concat("account_", ascii_digit(from_index)))
        Receiver: app_global_get(concat("account_", ascii_digit(to_index)))
        Amount: amount
        Fee: 0
    end
    return
end


@public()
func fund_fees():
    assert(Gtxn[-1].Receiver == Global.CurrentApplicationAddress)
    # TODO: assert other necessary stuff!
    app_global_put("fee_balance", app_global_get("fee_balance") + Gtxn[-1].Amount)
    return
end

#### ---------------------------------------- Internal Functions ---------------------------------------------- ####

func ascii_digit(i: int) bytes:
    return extract(7, 1, itob(i + 48))
end


func update_rewards_and_rate(delta: int):
	int algo_balance = full_balance()
    # TODO: change calculations to use wide math where necessary
	int new_rewards = (algo_balance - delta) - app_global_get("algo_balance")
	app_global_put("total_rewards", app_global_get("total_rewards") + new_rewards)
	int protocol_rewards = ((new_rewards * 100) / app_global_get("protocol_fee"))
	int new_protocol_talgo = calc_talgo(protocol_rewards) 
    app_global_put("protocol_talgo", app_global_get("protocol_talgo") + new_protocol_talgo)
    app_global_put("minted_talgo", app_global_get("minted_talgo") + new_protocol_talgo)
    app_global_put("algo_balance", (algo_balance - delta))
    if app_global_get("minted_talgo"):
        app_global_put("rate", (app_global_get("algo_balance") * RATE_SCALER) / app_global_get("minted_talgo"))
    else:
        app_global_put("rate", 1 * RATE_SCALER)
    end
    log(concat("%i", itob(app_global_get("rate"))))
    return
end


func calc_talgo(algo_amount: int) int:
	int talgo_amount = (algo_amount * RATE_SCALER) / app_global_get("rate")
    return talgo_amount
end


func calc_algo(talgo_amount: int) int:
	int algo_amount = (talgo_amount * app_global_get("rate")) / RATE_SCALER
    return algo_amount
end


func create_auxiliary_account(index: int):
    bytes key = concat("account_", ascii_digit(index))

    # 1. create application with program that rekeys to current app
    inner_txn:
        TypeEnum: Appl
        OnCompletion: NoOp
        ApprovalProgram: AUX_PROGRAM
        ClearStateProgram: "\x0A\x81\x01"
        GlobalNumUint: 1
        Fee: 0
    end
    int app_id = Itxn.CreatedApplicationID

    # 2. determine app address from the app id
    bytes address = sha512_256(concat("appID", itob(app_id)))
    app_global_put(key, address)

    # 3. fund account with mbr algo
    inner_txn:
        TypeEnum: Pay
        Receiver: address
        Amount: 100_000
        Fee: 0
    end
    return
end


func full_balance() int:
    int algo = 0
    algo = algo + balance(app_global_get("account_0"))
    algo = algo + balance(app_global_get("account_1"))
    algo = algo + balance(app_global_get("account_2"))
    algo = algo + balance(app_global_get("account_3"))
    algo = algo + balance(app_global_get("account_4"))
    algo = algo - app_global_get("initial_balance")
    algo = algo - app_global_get("fee_balance")
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
