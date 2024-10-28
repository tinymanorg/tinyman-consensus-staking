from algosdk import abi

from sdk.event import Event  # TODO: This dependency is copied from sdk.


user_state_event = Event(
    name="user_state",
    args=[
        abi.Argument(arg_type="address", name="user_address"),
        abi.Argument(arg_type="uint64", name="staked_amount"),
        abi.Argument(arg_type="uint64", name="accumulated_rewards_per_unit_at_last_update"),
        abi.Argument(arg_type="uint64", name="accumulated_rewards"),
        abi.Argument(arg_type="uint64", name="timestamp"),
    ]
)


create_application_event = Event(
    name="create_application",
    args=[
        abi.Argument(arg_type="uint64", name="talgo_asset_id"),
        abi.Argument(arg_type="uint64", name="tiny_asset_id"),
        abi.Argument(arg_type="uint64", name="vault_app_id"),
        abi.Argument(arg_type="address", name="manager_address"),
    ]
)


init_event = Event(
    name="event",
    args=[
        abi.Argument(arg_type="uint64", name="stalgo_asset_id")
    ]
)


state_event = Event(
    name="state",
    args=[
        abi.Argument(arg_type="uint64", name="last_update_timestamp"),
        abi.Argument(arg_type="uint64", name="current_reward_rate_per_time"),
        abi.Argument(arg_type="uint64", name="accumulated_rewards_per_unit"),
        abi.Argument(arg_type="uint64", name="total_staked_amount"),
    ]
)


update_state_event = Event(
    name="update_state",
    args=[
        abi.Argument(arg_type="uint64", name="timestamp"),
    ]
)


update_user_state_event = Event(
    name="update_user_state",
    args=[
        abi.Argument(arg_type="address", name="user_address"),
    ]
)


set_reward_rate_event = Event(
    name="set_reward_rate",
    args=[
        abi.Argument(arg_type="uint64", name="total_reward_amount"),
        abi.Argument(arg_type="uint64", name="start_timestamp"),
        abi.Argument(arg_type="uint64", name="end_timestamp"),
        abi.Argument(arg_type="uint64", name="current_reward_rate_per_time"),
    ]
)


apply_rate_change_event = Event(
    name="apply_rate_change",
    args=[
        abi.Argument(arg_type="uint64", name="current_reward_rate_per_time"),
    ]
)


increase_stake_event = Event(
    name="increase_stake",
    args=[
        abi.Argument(arg_type="uint64", name="amount"),
    ]
)


decrease_stake_event = Event(
    name="decrease_stake",
    args=[
        abi.Argument(arg_type="uint64", name="amount"),
    ]
)


claim_rewards_event = Event(
    name="increase_stake",
    args=[
        abi.Argument(arg_type="uint64", name="amount"),
    ]
)


restaking_events = [
    create_application_event,
    init_event,
    state_event,
    set_reward_rate_event,
    apply_rate_change_event,
    update_state_event,
    user_state_event,
    update_user_state_event,
    increase_stake_event,
    decrease_stake_event,
    claim_rewards_event
]