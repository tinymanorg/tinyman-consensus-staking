#pragma version 10
#tealish version git+https://github.com/Hipo/tealish.git@f1c2b72aaeb586ed082c380a638ed2e7ca47bcae

# Tinyman tAlgo
# License: https://github.com/tinymanorg/tinyman-consensus-staking/blob/main/LICENSE
# Documentation: https://docs.tinyman.org


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

const bytes TOTAL_REWARD_AMOUNT_SUM_KEY = "total_reward_amount_sum"
const bytes TOTAL_CLAIMED_REWARD_AMOUNT_KEY = "total_claimed_reward_amount"
const bytes CURRENT_REWARD_RATE_PER_TIME_KEY = "current_reward_rate_per_time"
const bytes CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY = "current_reward_rate_per_time_end_timestamp"
const bytes ACCUMULATED_REWARDS_PER_UNIT = "accumulated_rewards_per_unit"

const bytes TINY_POWER_THRESHOLD_KEY = "tiny_power_threshold"
const bytes LAST_UPDATE_TIMESTAMP_KEY = "last_update_timestamp"
const bytes TOTAL_STAKED_AMOUNT_KEY = "total_staked_amount"
const bytes TOTAL_STAKER_COUNT_KEY = "total_staker_count"

const bytes PROPOSED_MANAGER_KEY = "proposed_manager"
const bytes MANAGER_KEY = "manager"

const int RPU_SCALER = 1000000000
const int MAX_UINT64 = 18446744073709551615
const int ALGO_TOTAL_SUPPLY = 10000000000000000


router:
    create_application
    init
    propose_manager
    accept_manager
    set_tiny_power_threshold
    set_reward_rate
    apply_rate_change
    update_state
    increase_stake
    decrease_stake
    claim_rewards
end


# Permission: anyone
@public(OnCompletion=CreateApplication)
func create_application(talgo_asset_id: int, tiny_asset_id: int, vault_app_id: int, manager_address: bytes[32]):
    app_global_put(TALGO_ASSET_ID_KEY, talgo_asset_id)
    app_global_put(TINY_ASSET_ID_KEY, tiny_asset_id)
    app_global_put(VAULT_APP_ID_KEY, vault_app_id)
    app_global_put(MANAGER_KEY, manager_address)
    app_global_put(TINY_POWER_THRESHOLD_KEY, 500000000)

    app_global_put(CURRENT_REWARD_RATE_PER_TIME_KEY, 0)
    app_global_put(CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY, MAX_UINT64)
    app_global_put(TOTAL_CLAIMED_REWARD_AMOUNT_KEY, 0)

    # create_application(talgo_asset_id, tiny_asset_id, manager_address, stalgo_asset_id)
    log(ARC28Event("create_application(uint64,uint64,uint64,address)", itob(talgo_asset_id), itob(tiny_asset_id), itob(vault_app_id), manager_address))
    return
end


# Permission: manager
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
        ConfigAssetTotal: ALGO_TOTAL_SUPPLY
        ConfigAssetDecimals: 6
        ConfigAssetURL: "https://tinyman.org"
        ConfigAssetReserve: Global.CurrentApplicationAddress
		ConfigAssetClawback: Global.CurrentApplicationAddress
        ConfigAssetFreeze: Global.CurrentApplicationAddress
        ConfigAssetDefaultFrozen: 1
        Fee: 0
    end

    app_global_put(STALGO_ASSET_ID_KEY, Itxn.CreatedAssetID)

    log(ARC28Event("init(uint64)", itob(app_global_get(STALGO_ASSET_ID_KEY))))
    return
end


# permission: manager
@public()
func propose_manager(new_manager: bytes[32]):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    app_global_put(PROPOSED_MANAGER_KEY, new_manager)
    log(ARC28Event("propose_manager(address)", new_manager))
    return
end


# The proposed manager must call this function to become the manager.
# permission: proposed_manager
@public()
func accept_manager():
    bytes proposed_manager = app_global_get(PROPOSED_MANAGER_KEY)
    assert(Txn.Sender == proposed_manager)

    app_global_put(MANAGER_KEY, proposed_manager)
    app_global_put(PROPOSED_MANAGER_KEY, "")
    log(ARC28Event("accept_manager(address)", proposed_manager))
    return
end


# Permission: manager
@public()
func set_tiny_power_threshold(threshold: int):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    app_global_put(TINY_POWER_THRESHOLD_KEY, threshold)

    log(ARC28Event("set_tiny_power_threshold(uint64)", itob(threshold)))
    return
end


# Permission: manager
@public()
func set_reward_rate(total_reward_amount: int, end_timestamp: int):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    assert(total_reward_amount)
    assert(end_timestamp > Global.LatestTimestamp)

    # Wrap up, accumulate for the last rate.
    update_state_internal(Global.LatestTimestamp)

    int duration = end_timestamp - Global.LatestTimestamp
    int reward_rate_per_time = total_reward_amount / duration
    assert(reward_rate_per_time <= 18446744073)

    # Calculate the needed balance.
    int total_reward_amount_sum = app_global_get(TOTAL_REWARD_AMOUNT_SUM_KEY)
    int total_claimed_reward_amount = app_global_get(TOTAL_CLAIMED_REWARD_AMOUNT_KEY)
    int current_reward_rate_per_time_end_timestamp = app_global_get(CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY)

    if Global.LatestTimestamp < current_reward_rate_per_time_end_timestamp:
        int current_reward_rate_per_time = app_global_get(CURRENT_REWARD_RATE_PER_TIME_KEY)
        int remaining_from_current_rate = (current_reward_rate_per_time * (current_reward_rate_per_time_end_timestamp - Global.LatestTimestamp))

        # Subtract the amount that won't be distributed from the current rate.
        total_reward_amount_sum = total_reward_amount_sum - remaining_from_current_rate
    end

    total_reward_amount_sum = total_reward_amount_sum + total_reward_amount
    int balance_needed = total_reward_amount_sum - total_claimed_reward_amount

    # Check TINY balance such that it is enough for both unpaid rewards and future rewards.
    int tiny_balance
    _, tiny_balance = asset_holding_get(AssetBalance, Global.CurrentApplicationAddress, app_global_get(TINY_ASSET_ID_KEY))
    assert(tiny_balance >= balance_needed)

    app_global_put(TOTAL_REWARD_AMOUNT_SUM_KEY, total_reward_amount_sum)
    app_global_put(CURRENT_REWARD_RATE_PER_TIME_KEY, reward_rate_per_time)
    app_global_put(CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY, end_timestamp)

    # Logging
    int accumulated_rewards_per_unit = app_global_get(ACCUMULATED_REWARDS_PER_UNIT)
    int total_staked_amount = app_global_get(TOTAL_STAKED_AMOUNT_KEY)
    log(ARC28Event("state(uint64,uint64,uint64,uint64)", itob(Global.LatestTimestamp), itob(reward_rate_per_time), itob(accumulated_rewards_per_unit), itob(total_staked_amount)))

    log(ARC28Event("set_reward_rate(uint64,uint64,uint64,uint64)", itob(total_reward_amount), itob(Global.LatestTimestamp), itob(end_timestamp), itob(reward_rate_per_time)))
    return
end


# Description: If current rate expiration is reached, set it to 0.
# Permission: anyone.
@public()
func apply_rate_change():
    int reward_rate_per_time

    int current_reward_rate_per_time = app_global_get(CURRENT_REWARD_RATE_PER_TIME_KEY)
    int current_reward_rate_per_time_end_timestamp = app_global_get(CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY)

    int last_update_timestamp = app_global_get(LAST_UPDATE_TIMESTAMP_KEY)

    if Global.LatestTimestamp <= current_reward_rate_per_time_end_timestamp:
        # Do nothing. CURRENT_REWARD_RATE_PER_TIME is valid.
        reward_rate_per_time = current_reward_rate_per_time

    else:
        update_state_internal(current_reward_rate_per_time_end_timestamp)

        # Update the CURRENT_REWARD_RATE_PER_TIME to 0.
        app_global_put(CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY, MAX_UINT64)
        app_global_put(CURRENT_REWARD_RATE_PER_TIME_KEY, 0)

        reward_rate_per_time = 0

        # Logging
        int accumulated_rewards_per_unit = app_global_get(ACCUMULATED_REWARDS_PER_UNIT)
        int total_staked_amount = app_global_get(TOTAL_STAKED_AMOUNT_KEY)
        log(ARC28Event("state(uint64,uint64,uint64,uint64)", itob(current_reward_rate_per_time_end_timestamp), itob(reward_rate_per_time), itob(accumulated_rewards_per_unit), itob(total_staked_amount)))

        log(ARC28Event("apply_rate_change(uint64)", itob(reward_rate_per_time)))
    end

    return
end


# Validate and get CURRENT_REWARD_RATE_PER_TIME value. Timestamp is parameterized for the call in `apply_rate_change`.
# It is ensured that timestamp is not in past in `update_state`.
func get_reward_rate_per_time(timestamp: int) int:
    int current_reward_rate_per_time = app_global_get(CURRENT_REWARD_RATE_PER_TIME_KEY)
    int current_reward_rate_per_time_end_timestamp = app_global_get(CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY)

    # Ensure CURRENT_REWARD_RATE_PER_TIME is disabled or still valid.
    assert(timestamp <= current_reward_rate_per_time_end_timestamp)

    return current_reward_rate_per_time
end


# Description: Accumulate rewards. Fails if there is a pending rate change.
# Permission: anyone.
@public()
func update_state():
    update_state_internal(Global.LatestTimestamp)

    # Logging
    int reward_rate_per_time = get_reward_rate_per_time(Global.LatestTimestamp)
    int accumulated_rewards_per_unit = app_global_get(ACCUMULATED_REWARDS_PER_UNIT)
    int total_staked_amount = app_global_get(TOTAL_STAKED_AMOUNT_KEY)
    log(ARC28Event("state(uint64,uint64,uint64,uint64)", itob(Global.LatestTimestamp), itob(reward_rate_per_time), itob(accumulated_rewards_per_unit), itob(total_staked_amount)))

    return
end


func update_state_internal(timestamp: int):
    int last_update_timestamp = app_global_get(LAST_UPDATE_TIMESTAMP_KEY)
    int accumulated_rewards_per_unit = app_global_get(ACCUMULATED_REWARDS_PER_UNIT)
    int total_staked_amount = app_global_get(TOTAL_STAKED_AMOUNT_KEY)

    int reward_rate_per_time = get_reward_rate_per_time(timestamp)

    assert(last_update_timestamp <= timestamp)
    if total_staked_amount:
        int time_delta = timestamp - last_update_timestamp

        # This would overflow if reward_rate_per_time > 18446744073 microunit.
        # This is asserted in set_reward_rate.
        int reward_rate_per_unit_per_time = (reward_rate_per_time * RPU_SCALER) / total_staked_amount
        accumulated_rewards_per_unit = accumulated_rewards_per_unit + (reward_rate_per_unit_per_time * time_delta)

        app_global_put(ACCUMULATED_REWARDS_PER_UNIT, accumulated_rewards_per_unit)
    end

    app_global_put(LAST_UPDATE_TIMESTAMP_KEY, timestamp)

    return
end


# Description: Accumulate user rewards. Should be called after `update_state`.
func update_user_state(user_address: bytes[32]):
    int rewards_per_unit_delta
    int rewards_delta

    box<UserState> user_state = OpenBox(user_address)

    int last_update_timestamp = app_global_get(LAST_UPDATE_TIMESTAMP_KEY)
    int accumulated_rewards_per_unit = app_global_get(ACCUMULATED_REWARDS_PER_UNIT)
    int total_staked_amount = app_global_get(TOTAL_STAKED_AMOUNT_KEY)

    rewards_per_unit_delta = accumulated_rewards_per_unit - user_state.accumulated_rewards_per_unit_at_last_update
    rewards_delta = btoi((itob(user_state.staked_amount) b* itob(rewards_per_unit_delta)) b/ itob(RPU_SCALER))

    user_state.accumulated_rewards = user_state.accumulated_rewards + rewards_delta
    user_state.accumulated_rewards_per_unit_at_last_update = accumulated_rewards_per_unit
    user_state.timestamp = Global.LatestTimestamp

    return
end


# Permission: user
@public()
func increase_stake(amount: int):
    int total_staker_count
    int current_tiny_power

    box<UserState> user_state = OpenOrCreateBox(Txn.Sender)

    assert(amount > 0)

    update_state_internal(Global.LatestTimestamp)
    update_user_state(Txn.Sender)

    check_received_talgo(Txn.GroupIndex - 1, amount)

    if !user_state.staked_amount:
        current_tiny_power = get_account_voting_power(Txn.Sender)
        assert(current_tiny_power >= app_global_get(TINY_POWER_THRESHOLD_KEY))

        total_staker_count = app_global_get(TOTAL_STAKER_COUNT_KEY)
        total_staker_count = total_staker_count + 1
        app_global_put(TOTAL_STAKER_COUNT_KEY, total_staker_count)
    end

    user_state.staked_amount = user_state.staked_amount + amount
    send_stalgo(amount, Txn.Sender)

    int total_staked_amount = app_global_get(TOTAL_STAKED_AMOUNT_KEY)
    total_staked_amount = total_staked_amount + amount
    app_global_put(TOTAL_STAKED_AMOUNT_KEY, total_staked_amount)

    # Logging
    int reward_rate_per_time = get_reward_rate_per_time(Global.LatestTimestamp)
    int accumulated_rewards_per_unit = app_global_get(ACCUMULATED_REWARDS_PER_UNIT)
    log(ARC28Event("state(uint64,uint64,uint64,uint64)", itob(Global.LatestTimestamp), itob(reward_rate_per_time), itob(accumulated_rewards_per_unit), itob(total_staked_amount)))

    bytes user_state_data
    _, user_state_data = box_get(user_state)
    log(ARC28Event("user_state(address,uint64,uint64,uint64,uint64)", Txn.Sender, user_state_data))
    log(ARC28Event("increase_stake(uint64)", itob(amount)))
    return
end


# Permission: user
@public()
func decrease_stake(amount: int):
    int total_staker_count

    box<UserState> user_state = OpenBox(Txn.Sender)

    update_state_internal(Global.LatestTimestamp)
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

    # Logging
    int reward_rate_per_time = get_reward_rate_per_time(Global.LatestTimestamp)
    int accumulated_rewards_per_unit = app_global_get(ACCUMULATED_REWARDS_PER_UNIT)
    log(ARC28Event("state(uint64,uint64,uint64,uint64)", itob(Global.LatestTimestamp), itob(reward_rate_per_time), itob(accumulated_rewards_per_unit), itob(total_staked_amount)))

    bytes user_state_data
    _, user_state_data = box_get(user_state)
    log(ARC28Event("user_state(address,uint64,uint64,uint64,uint64)", Txn.Sender, user_state_data))
    log(ARC28Event("decrease_stake(uint64)", itob(amount)))
    return
end


# Permission: user
@public()
func claim_rewards():
    box<UserState> user_state = OpenBox(Txn.Sender)

    update_state_internal(Global.LatestTimestamp)
    update_user_state(Txn.Sender)

    int amount = user_state.accumulated_rewards
    if amount:
        int current_tiny_power = get_account_voting_power(Txn.Sender)
        assert(current_tiny_power >= app_global_get(TINY_POWER_THRESHOLD_KEY))

        int total_claimed_reward_amount = app_global_get(TOTAL_CLAIMED_REWARD_AMOUNT_KEY)
        total_claimed_reward_amount = total_claimed_reward_amount + amount
        app_global_put(TOTAL_CLAIMED_REWARD_AMOUNT_KEY, total_claimed_reward_amount)

        send_rewards(amount, Txn.Sender)
        user_state.accumulated_rewards = 0
    end

    # Logging
    int reward_rate_per_time = get_reward_rate_per_time(Global.LatestTimestamp)
    int accumulated_rewards_per_unit = app_global_get(ACCUMULATED_REWARDS_PER_UNIT)
    int total_staked_amount = app_global_get(TOTAL_STAKED_AMOUNT_KEY)
    log(ARC28Event("state(uint64,uint64,uint64,uint64)", itob(Global.LatestTimestamp), itob(reward_rate_per_time), itob(accumulated_rewards_per_unit), itob(total_staked_amount)))

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
        AssetSender: Global.CurrentApplicationAddress
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
