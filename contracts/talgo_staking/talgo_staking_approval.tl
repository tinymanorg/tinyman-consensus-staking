#pragma version 9

# Name: <index>
# Size: 24 bytes
struct RewardPeriod:
    total_reward_amount: int
    start_timestamp: int
    end_timestamp: int
end

# Name: <user_address>
struct UserState:
    staked_amount: int
    accumulated_rewards_per_unit_at_last_update: int
    accumulated_rewards: int
    timestamp: int
end

# Global State

const bytes VAULT_APP_ID_KEY = "vault_app_id"
const bytes TINY_ASSET_ID_KEY = "tiny_asset_id"
const bytes TALGO_ASSET_ID_KEY = "talgo_asset_id"
const bytes STALGO_ASSET_ID_KEY = "stalgo_asset_id"
const bytes PERIOD_COUNT_KEY = "period_count"
const bytes CURRENT_PERIOD_INDEX_KEY = "current_period_index"

const bytes TINY_POWER_THRESHOLD_KEY = "tiny_power_threshold"
const bytes LAST_UPDATE_TIMESTAMP_KEY = "last_update_timestamp"
const bytes ACCUMULATED_REWARDS_PER_UNIT = "accumulated_rewards_per_unit"
const bytes CURRENT_REWARD_RATE_PER_TIME_KEY = "current_reward_rate_per_time"
const bytes TOTAL_STAKED_AMOUNT_KEY = "total_staked_amount"
const bytes TOTAL_STAKER_COUNT_KEY = "total_staker_count"

const bytes MANAGER_KEY = "manager"

const int RPU_SCALER = 1000000000
const int POOL_TOKEN_TOTAL_SUPPLY = 18446744073709551615
const int MAX_UINT64 = 18446744073709551615


router:
    create_application
    update_application
    create_reward_period
    set_tiny_power_threshold
    update_state
    increase_stake
    decrease_stake
    claim_rewards
end


# TODO: This should be removed.
@public(OnCompletion=UpdateApplication)
func update_application():
	bytes manager_address = app_global_get(MANAGER_KEY)
	assert(Txn.Sender == manager_address)
    return
end


@public(OnCompletion=CreateApplication)
func create_application(talgo_asset_id: int, tiny_asset_id: int, vault_app_id: int, manager_address: bytes[32]):
    app_global_put(TALGO_ASSET_ID_KEY, talgo_asset_id)
	app_global_put(TINY_ASSET_ID_KEY, tiny_asset_id)
    app_global_put(VAULT_APP_ID_KEY, vault_app_id)
	app_global_put(MANAGER_KEY, manager_address)
    app_global_put(TINY_POWER_THRESHOLD_KEY, 1000)

	# create_application(talgo_asset_id, tiny_asset_id, manager_address, stalgo_asset_id)
	log(ARC28Event("create_application(uint64,uint64,uint64,address)", itob(talgo_asset_id), itob(tiny_asset_id), itob(vault_app_id), manager_address))
    return
end


@public()
func init():
    assert(Txn.Sender == app_global_get(MANAGER_KEY))
    assert(!app_global_get(STALGO_ASSET_ID_KEY))

    opt_in_to_asset(app_global_get(TINY_ASSET_ID_KEY))
    opt_in_to_asset(app_global_get(TALGO_ASSET_ID_KEY))

    inner_txn:
        TypeEnum: Acfg
        Sender: Global.CurrentApplicationAddress
        ConfigAssetUnitName: "STALGO"
        ConfigAssetName: "Staked tALGO"
        ConfigAssetTotal: POOL_TOKEN_TOTAL_SUPPLY
        ConfigAssetDecimals: 6
        ConfigAssetURL: "https://tinyman.org"
        ConfigAssetReserve: Global.CurrentApplicationAddress
		ConfigAssetClawback: Global.CurrentApplicationAddress
        ConfigAssetFreeze: Global.CurrentApplicationAddress
        ConfigAssetDefaultFrozen: 1
        Fee: 0
    end

    app_global_put(STALGO_ASSET_ID_KEY, Itxn.CreatedAssetID)

    log(ARC28Event("init(uint64)", itob(app_global_get("STALGO_ASSET_ID_KEY"))))
    return
end


@public()
func create_reward_period(total_reward_amount: int, start_timestamp: int, end_timestamp: int):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    assert(total_reward_amount)
    assert(start_timestamp >= Global.LatestTimestamp)
    assert(end_timestamp > start_timestamp)

    int period_count = app_global_get(PERIOD_COUNT_KEY)

    box<RewardPeriod> reward_period = CreateBox(itob(period_count))
    reward_period.total_reward_amount = total_reward_amount
    reward_period.start_timestamp = start_timestamp
    reward_period.end_timestamp = end_timestamp

    period_count = period_count + 1
    app_global_put(PERIOD_COUNT_KEY, period_count)

    log(ARC28Event("reward_period(uint64,uint64,uint64)", itob(total_reward_amount), itob(start_timestamp), itob(end_timestamp)))
    log(ARC28Event("create_reward_period(uint64)", itob(period_count)))
    return
end


@public()
func set_tiny_power_threshold(threshold: int):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    app_global_put(TINY_POWER_THRESHOLD_KEY, threshold)

    log(ARC28Event("set_tiny_power_threshold(uint64)", itob(threshold)))
    return
end


@public()
func update_state(period_index: int):
    int current_period_index = app_global_get(CURRENT_PERIOD_INDEX_KEY)
    box<RewardPeriod> current_reward_period = OpenBox(itob(current_period_index))

    if current_period_index != period_index:
        assert(current_reward_period.end_timestamp <= Global.LatestTimestamp)

        box<RewardPeriod> new_reward_period = OpenBox(itob(period_index))
        assert(new_reward_period.start_timestamp <= Global.LatestTimestamp)
        assert(new_reward_period.end_timestamp > Global.LatestTimestamp)

        app_global_put(CURRENT_PERIOD_INDEX_KEY, period_index)
        current_reward_period = new_reward_period

        int duration = current_reward_period.end_timestamp - current_reward_period.start_timestamp
        int reward_rate_per_time = current_reward_period.total_reward_amount / duration
        app_global_put(CURRENT_REWARD_RATE_PER_TIME_KEY, reward_rate_per_time)
    else:
        assert(current_reward_period.end_timestamp <= Global.LatestTimestamp)
    end

    int last_update_timestamp = app_global_get(LAST_UPDATE_TIMESTAMP_KEY)
    int current_reward_rate_per_time = app_global_get(CURRENT_REWARD_RATE_PER_TIME_KEY)
    int accumulated_rewards_per_unit = app_global_get(ACCUMULATED_REWARDS_PER_UNIT)
    int total_staked_amount = app_global_get(TOTAL_STAKED_AMOUNT_KEY)
    
    int time_delta = Global.LatestTimestamp -  last_update_timestamp

    int reward_rate_per_unit_per_time = (reward_rate_per_time * RPU_SCALER) / total_staked_amount
    accumulated_rewards_per_unit = accumulated_rewards_per_unit + (reward_rate_per_unit_per_time * time_delta)

    app_global_put(LAST_UPDATE_TIMESTAMP_KEY, Global.LatestTimestamp)
    app_global_put(ACCUMULATED_REWARDS_PER_UNIT, accumulated_rewards_per_unit)

    log(ARC28Event("state(uint64,uint64,uint64,uint64)", itob(last_update_timestamp), itob(current_reward_rate_per_time), itob(accumulated_rewards_per_unit), itob(total_staked_amount)))
    log(ARC28Event("update_state(uint64)", itob(period_index)))
    return
end


func update_user_state(user_address: bytes[32]):
    int rewards_per_unit_delta
    int rewards_delta

    box<UserState> user_state = OpenBox(user_address)

    int last_update_timestamp = app_global_get(LAST_UPDATE_TIMESTAMP_KEY)
    int current_reward_rate_per_time = app_global_get(CURRENT_REWARD_RATE_PER_TIME_KEY)
    int accumulated_rewards_per_unit = app_global_get(ACCUMULATED_REWARDS_PER_UNIT)
    int total_staked_amount = app_global_get(TOTAL_STAKED_AMOUNT_KEY)

    rewards_per_unit_delta = accumulated_rewards_per_unit - user_state.accumulated_rewards_per_unit_at_last_update
    rewards_delta = (user_state.staked_amount * rewards_per_unit_delta) / RPU_SCALER

    user_state.accumulated_rewards = user_state.accumulated_rewards + rewards_delta
    user_state.accumulated_rewards_per_unit_at_last_update = accumulated_rewards_per_unit
    user_state.timestamp = Global.LatestTimestamp

    bytes user_state_data
    _, user_state_data = box_get(user_state)
    log(ARC28Event("user_state(address,uint64,uint64,uint64,uint64)", Txn.Sender, user_state_data))
    log(ARC28Event("update_user_state(address)", Txn.Sender))
    return
end


@public()
func increase_stake(amount: int):
    int total_staker_count
    int current_tiny_power

    box<UserState> user_state = OpenOrCreateBox(Txn.Sender)

    update_state(app_global_get(CURRENT_PERIOD_INDEX_KEY))
    update_user_state(Txn.Sender)

    check_received_talgo(Txn.GroupIndex - 1, amount)
    user_state.staked_amount = user_state.staked_amount + amount

    send_stalgo(amount, Txn.Sender)

    if !user_state.staked_amount:
        current_tiny_power = get_account_voting_power(Txn.Sender)
        assert(current_tiny_power >= app_global_get(TINY_POWER_THRESHOLD_KEY))

        total_staker_count = app_global_get(TOTAL_STAKER_COUNT_KEY)
        total_staker_count = total_staker_count + 1
        app_global_put(TOTAL_STAKER_COUNT_KEY, total_staker_count)
    end

    int total_staked_amount = app_global_get(TOTAL_STAKED_AMOUNT_KEY)
    total_staked_amount = total_staked_amount + amount
    app_global_put(TOTAL_STAKED_AMOUNT_KEY, total_staked_amount)

    bytes user_state_data
    _, user_state_data = box_get(user_state)
    log(ARC28Event("user_state(address,uint64,uint64,uint64,uint64)", Txn.Sender, user_state_data))
    log(ARC28Event("increase_stake(uint64)", itob(amount)))
    return
end


@public()
func decrease_stake(amount: int):
    int total_staker_count

    box<UserState> user_state = OpenBox(Txn.Sender)

    update_state(app_global_get(CURRENT_PERIOD_INDEX_KEY))
    update_user_state(Txn.Sender)

    assert(amount > 0)
    assert(amount <= user_state.staked_amount)

    user_state.staked_amount = user_state.staked_amount - amount
    clawback_stalgo(amount, Txn.Sender)

    send_talgo(amount, Txn.Sender)

    if !user_state.staked_amount:
        total_staker_count = app_global_get(TOTAL_STAKER_COUNT_KEY)
        total_staker_count = total_staker_count - 1
        app_global_put(TOTAL_STAKER_COUNT_KEY, total_staker_count)
    end

    int total_staked_amount = app_global_get(TOTAL_STAKED_AMOUNT_KEY)
    total_staked_amount = total_staked_amount - amount
    app_global_put(TOTAL_STAKED_AMOUNT_KEY, total_staked_amount)

    bytes user_state_data
    _, user_state_data = box_get(user_state)
    log(ARC28Event("user_state(address,uint64,uint64,uint64,uint64)", Txn.Sender, user_state_data))
    log(ARC28Event("decrease_stake(uint64)", itob(amount)))
    return
end


@public()
func claim_rewards():
    box<UserState> user_state = OpenBox(Txn.Sender)

    update_state(app_global_get(CURRENT_PERIOD_INDEX_KEY))
    update_user_state(Txn.Sender)

    int amount = user_state.accumulated_rewards
    if amount:
        send_rewards(amount, Txn.Sender)
        user_state.accumulated_rewards = 0
    end

    bytes user_state_data
    _, user_state_data = box_get(user_state)
    log(ARC28Event("user_state(address,uint64,uint64,uint64,uint64)", Txn.Sender, user_state_data))
    log(ARC28Event("claim_rewards(uint64)", itob(amount)))
    return
end


func send_stalgo(amount: int, receiver: bytes[32]):
    inner_txn:
        TypeEnum: Axfer
        Sender: Global.CurrentApplicationAddress
        AssetReceiver: receiver
        AssetAmount: amount
        XferAsset: app_global_get(STALGO_ASSET_ID_KEY)
        Fee: 0
    end

    return
end


func send_talgo(amount: int, receiver: bytes[32]):
    inner_txn:
        TypeEnum: Axfer
        Sender: Global.CurrentApplicationAddress
        AssetReceiver: receiver
        AssetAmount: amount
        XferAsset: app_global_get(TALGO_ASSET_ID_KEY)
        Fee: 0
    end

    return
end


func send_rewards(amount: int, receiver: bytes[32]):
    inner_txn:
        TypeEnum: Axfer
        Sender: Global.CurrentApplicationAddress
        AssetReceiver: receiver
        AssetAmount: amount
        XferAsset: app_global_get(TINY_ASSET_ID_KEY)
        Fee: 0
    end

    return
end


func clawback_stalgo(amount: int, user: bytes[32]):
    inner_txn:
        TypeEnum: Axfer
		Sender: Global.CurrentApplicationAddress
        AssetSender: user
        AssetReceiver: Global.CurrentApplicationAddress
        AssetAmount: amount
        XferAsset: app_global_get(STALGO_ASSET_ID_KEY)
        Fee: 0
    end
    return
end


func check_received_talgo(txn_index: int, amount: int):
    assert(Gtxn[txn_index].TypeEnum == Axfer)
    assert(Gtxn[txn_index].AssetReceiver == Global.CurrentApplicationAddress)
    assert(Gtxn[txn_index].AssetAmount == amount)
    assert(Gtxn[txn_index].XferAsset == app_global_get(TALGO_ASSET_ID_KEY))

    return
end


func get_account_voting_power(address: bytes[32]) int:
    inner_txn:
        TypeEnum: Appl
        ApplicationID: app_global_get(VAULT_APP_ID_KEY)
        ApplicationArgs[0]: "get_tiny_power_of"
        ApplicationArgs[1]: address
        Fee: 0
    end
    int voting_power = extract_uint64(Itxn.LastLog, 4)
    return voting_power
end


func opt_in_to_asset(asset_id: int):
    inner_txn:
        TypeEnum: Axfer
        Sender: Global.CurrentApplicationAddress
        AssetReceiver: Global.CurrentApplicationAddress
        AssetAmount: 0
        XferAsset: asset_id
        Fee: 0
    end

    return
end
