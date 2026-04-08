# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Deploy Buddy Environment Client."""

from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

from .models import DeployBuddyAction, DeployBuddyObservation


class DeployBuddyEnv(
    EnvClient[DeployBuddyAction, DeployBuddyObservation, State]
):
    """
    Client for the Deploy Buddy Environment.
    """

    def _step_payload(self, action: DeployBuddyAction) -> Dict:
        # No need to manually inject; model_dump() handles it now
        return action.model_dump()

    def _parse_result(self, payload: Dict) -> StepResult[DeployBuddyObservation]:
        """
        Parse server response into StepResult.
        """
        obs_data = payload.get("observation", {})

        observation = DeployBuddyObservation(
            metrics=obs_data.get("metrics", {}),
            logs=obs_data.get("logs", []),
            alerts=obs_data.get("alerts", []),
            step=obs_data.get("step", 0),
            done=obs_data.get("done", False),
            reward=obs_data.get("reward", 0.0),
            metadata=obs_data.get("metadata", {}),
            grades_data=obs_data.get("grades_data", {})
        )

        return StepResult(
            observation=observation,
            reward=payload.get("reward", 0.0),
            done=payload.get("done", False)
        )

    def _parse_state(self, payload: Dict) -> State:
        """
        Parse server response into State object.
        """
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )

    async def evaluate(self) -> Dict:
        """
        Call evaluate endpoint on server.
        """
        response = await self._request("POST", "/evaluate", {})
        return response.get("data", {})
    
    async def grade(self) -> Dict:
        """
        Call the /grade endpoint on the server.
        """
        response = await self._send_and_receive({
            "type": "grade"
        })
        return response.get("data", {})