from dataclasses import dataclass
from datetime import datetime, timezone

from sdk.constants import *


@dataclass
class TAlgoStakingAppGlobalState:
    last_reward_rate_per_time: int
    current_reward_rate_per_time: int
    current_reward_rate_per_time_end_timestamp: int
    accumulated_rewards_per_unit: int
    total_staked_amount: int
    total_staker_count: int
    last_update_timestamp: int

    manager: str = None

    @classmethod
    def from_globalstate(cls, global_state: dict):
        return cls(
            last_reward_rate_per_time=global_state[LAST_REWARD_RATE_PER_TIME_KEY],
            current_reward_rate_per_time=global_state[CURRENT_REWARD_RATE_PER_TIME_KEY],
            current_reward_rate_per_time_end_timestamp=global_state[CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY],
            accumulated_rewards_per_unit=global_state[ACCUMULATED_REWARDS_PER_UNIT],
            total_staked_amount=global_state[TOTAL_STAKED_AMOUNT_KEY],
            total_staker_count=global_state[TOTAL_STAKER_COUNT_KEY],
            last_update_timestamp=global_state[LAST_UPDATE_TIMESTAMP_KEY],
            manager=global_state[MANAGER_KEY],
        )

    def get_current_reward_rate_per_time(self, current_timestamp=None):
        if current_timestamp is None:
            current_timestamp = int(datetime.now(tz=timezone.utc).timestamp())

        assert(self.last_update_timestamp <= current_timestamp)

        if self.current_reward_rate_per_time_end_timestamp < current_timestamp:
            return 0

        return self.current_reward_rate_per_time

    def get_accumulated_rewards_per_unit(self, current_timestamp=None):
        if current_timestamp is None:
            current_timestamp = int(datetime.now(tz=timezone.utc).timestamp())
        
        time_delta = current_timestamp - self.last_update_timestamp
        reward_rate_per_unit_per_time = (self.get_current_reward_rate_per_time(current_timestamp) * 1_000_000_000) // self.total_staked_amount
        return self.accumulated_rewards_per_unit + (reward_rate_per_unit_per_time * time_delta)


def get_accumulated_rewards(user_state, global_state: TAlgoStakingAppGlobalState, current_timestamp=None):
    if current_timestamp is None:
            current_timestamp = int(datetime.now(tz=timezone.utc).timestamp())
    
    assert(user_state.timestamp <= current_timestamp)

    """
    rewards_per_unit_delta = accumulated_rewards_per_unit - user_state.accumulated_rewards_per_unit_at_last_update
    rewards_delta = btoi((itob(user_state.staked_amount) b* itob(rewards_per_unit_delta)) b/ itob(RPU_SCALER))
    """

    rewards_per_unit_delta = global_state.get_accumulated_rewards_per_unit(current_timestamp) - user_state.accumulated_rewards_per_unit_at_last_update
    rewards_delta = (user_state.staked_amount * rewards_per_unit_delta) // 1_000_000_000

    return user_state.accumulated_rewards + rewards_delta
