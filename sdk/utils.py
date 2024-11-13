from dataclasses import dataclass
from datetime import datetime, timezone

from sdk.constants import *


@dataclass
class TAlgoStakingAppGlobalState:
    total_reward_amount_sum: int
    total_claimed_reward_amount: int
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
            total_reward_amount_sum=global_state.get(TOTAL_REWARD_AMOUNT_SUM_KEY, 0),
            total_claimed_reward_amount=global_state.get(TOTAL_CLAIMED_REWARD_AMOUNT_KEY, 0),
            current_reward_rate_per_time=global_state.get(CURRENT_REWARD_RATE_PER_TIME_KEY, 0),
            current_reward_rate_per_time_end_timestamp=global_state.get(CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY, 0),
            accumulated_rewards_per_unit=global_state.get(ACCUMULATED_REWARDS_PER_UNIT, 0),
            total_staked_amount=global_state.get(TOTAL_STAKED_AMOUNT_KEY, 0),
            total_staker_count=global_state.get(TOTAL_STAKER_COUNT_KEY, 0),
            last_update_timestamp=global_state.get(LAST_UPDATE_TIMESTAMP_KEY, 0),
            manager=global_state[MANAGER_KEY],
        )

    def to_globalstate(self) -> dict:
        return {
            TOTAL_REWARD_AMOUNT_SUM_KEY: self.total_reward_amount_sum,
            TOTAL_CLAIMED_REWARD_AMOUNT_KEY: self.total_claimed_reward_amount,
            CURRENT_REWARD_RATE_PER_TIME_KEY: self.current_reward_rate_per_time,
            CURRENT_REWARD_RATE_PER_TIME_END_TIMESTAMP_KEY: self.current_reward_rate_per_time_end_timestamp,
            ACCUMULATED_REWARDS_PER_UNIT: self.accumulated_rewards_per_unit,
            TOTAL_STAKED_AMOUNT_KEY: self.total_staked_amount,
            TOTAL_STAKER_COUNT_KEY: self.total_staker_count,
            LAST_UPDATE_TIMESTAMP_KEY: self.last_update_timestamp,
            MANAGER_KEY: self.manager,
        }

    def get_current_reward_rate_per_time(self, current_timestamp=None):
        if current_timestamp is None:
            current_timestamp = int(datetime.now(tz=timezone.utc).timestamp())

        assert(self.last_update_timestamp <= current_timestamp)

        if self.current_reward_rate_per_time_end_timestamp < current_timestamp:
            return 0

        return self.current_reward_rate_per_time

    def calculate_accumulated_rewards_per_unit_delta(self, last_update_timestamp, current_timestamp, current_reward_rate_per_time):
        if self.total_staked_amount:
            time_delta = current_timestamp - last_update_timestamp
            reward_rate_per_unit_per_time = (current_reward_rate_per_time * 1_000_000_000) // self.total_staked_amount
            return (reward_rate_per_unit_per_time * time_delta)
        return 0

    def get_accumulated_rewards_per_unit(self, current_timestamp=None):
        if current_timestamp is None:
            current_timestamp = int(datetime.now(tz=timezone.utc).timestamp())

        arpu_delta = 0
        if current_timestamp > self.current_reward_rate_per_time_end_timestamp:
            # If there is a rate expiration, split the calculation.

            arpu_delta += self.calculate_accumulated_rewards_per_unit_delta(
                last_update_timestamp=self.last_update_timestamp,
                current_timestamp=self.current_reward_rate_per_time_end_timestamp,
                current_reward_rate_per_time=self.get_current_reward_rate_per_time(self.current_reward_rate_per_time_end_timestamp)
            )
            arpu_delta += self.calculate_accumulated_rewards_per_unit_delta(
                last_update_timestamp=self.current_reward_rate_per_time_end_timestamp,
                current_timestamp=current_timestamp,
                current_reward_rate_per_time=self.get_current_reward_rate_per_time(current_timestamp)
            )
        else:
            arpu_delta += self.calculate_accumulated_rewards_per_unit_delta(
                last_update_timestamp=self.last_update_timestamp,
                current_timestamp=current_timestamp,
                current_reward_rate_per_time=self.get_current_reward_rate_per_time(current_timestamp)
            )

        return self.accumulated_rewards_per_unit + arpu_delta


def get_accumulated_rewards(user_state, global_state: TAlgoStakingAppGlobalState, current_timestamp=None):
    if current_timestamp is None:
            current_timestamp = int(datetime.now(tz=timezone.utc).timestamp())
    
    assert(user_state.timestamp <= current_timestamp)

    rewards_per_unit_delta = global_state.get_accumulated_rewards_per_unit(current_timestamp) - user_state.accumulated_rewards_per_unit_at_last_update
    rewards_delta = (user_state.staked_amount * rewards_per_unit_delta) // 1_000_000_000

    return user_state.accumulated_rewards + rewards_delta
