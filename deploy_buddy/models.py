# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Data models for the Deploy Buddy Environment.

The deploy_buddy environment is a simple test environment that echoes back messages.
"""

from typing import Any, Dict, List, Literal, Optional
from openenv.core.env_server.types import Action, Observation
from pydantic import Field


class DeployBuddyAction(Action):
    """Structured action for SRE environment"""

    action_type: Literal[
        "inspect_service",
        "inspect_logs",
        "scale_service",
        "restart_service",
        "revert_version",
        "wait",
        "scale_down_service"
    ] = Field(..., description="Type of action")

    target: Optional[str] = Field(
        default=None,
        description="Target service (api, db, task_runner)"
    )

    value: Optional[int] = Field(
        default=None,
        description="Used for scaling (number of replicas)"
    )

    grade: bool = Field(
        default=False,
        description="enable grading/ evaluation"
    )


class DeployBuddyObservation(Observation):
    """Observation for SRE environment"""

    metrics: Dict[str, float] = Field(
        default_factory=dict,
        description="System metrics like latency, cpu, error_rate"
    )

    logs: List[str] = Field(
        default_factory=list,
        description="Sampled logs"
    )

    alerts: List[str] = Field(
        default_factory=list,
        description="Active alerts"
    )

    step: int = Field(
        default=0,
        description="Current timestep"
    )

    task_id: int = Field(default=0)

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional data like grading results"
    )
