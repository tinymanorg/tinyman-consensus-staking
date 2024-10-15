#pragma version 10

const int TALGO_TOTAL_SUPPLY = 10000000000000000
const int RATE_SCALER = 1000000
const bytes AUX_PROGRAM = "\n1\x18\x81\x00\x12D\xb1\x81\x01\xb2\x101\x00\xb2\x071\x00\xb2 \x81\x00\xb2\x01\xb3\x81\x01C"

# TODO:
# go_online
# go_offline
# set_node_manager
# set_protocol_fee

router:
    create_application
    init
    mint
    burn
    sync
    claim_protocol_rewards
    move_stake
end


#### ---------------------------------------- Public Functions ---------------------------------------------- ####


@public(OnCompletion=CreateApplication)
func create_application(manager_address: bytes[32]):
	app_global_put("manager", manager_address)
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
func move_stake(from_index: int, to_index: int, amount: int):
    inner_txn:
        TypeEnum: Pay
        Sender: app_global_get(concat("account_", extract(7, 1, itob(from_index + 48))))
        Receiver: app_global_get(concat("account_", extract(7, 1, itob(to_index + 48))))
        Amount: amount
        Fee: 0
    end
    return
end


@public()
func mint(algo_amount: int):
    assert(algo_amount == Gtxn[-1].Amount)
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

#### ---------------------------------------- Internal Functions ---------------------------------------------- ####

func update_rewards_and_rate(delta: int):
	int algo_balance = full_balance()
	int new_rewards = (algo_balance - delta) - app_global_get("algo_balance")
	app_global_put("total_rewards", app_global_get("total_rewards") + new_rewards)
	int protocol_rewards = (new_rewards / 10)
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
    bytes index_ascii = extract(7, 1, itob(index + 48))
    bytes key = concat("account_", index_ascii)

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
    return algo
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
    # TODO: set source account index
    int from_index = 0
    inner_txn:
        TypeEnum: Pay
        Sender: app_global_get(concat("account_", extract(7, 1, itob(from_index + 48))))
        Receiver: receiver
        Amount: amount
        Fee: 0
    end
    return
end
