# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.

"""
Deploy Buddy Environment - SRE Incident Simulation.

Simulates a distributed system where an agent must diagnose and fix
production issues like DB overload using actions such as scaling,
restarting services, etc.
"""

from uuid import uuid4
from copy import deepcopy
import random

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

from models import DeployBuddyAction, DeployBuddyObservation
from .tasks import EasyDBOverloadTask, MediumMemoryLeakTask, HardFeedbackLoopTask


class DeployBuddyEnvironment(Environment):
    """
    SRE-style environment for incident diagnosis and mitigation.

    The agent observes metrics/logs and performs actions to stabilize the system.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self):
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._internal_state = {}
        self.task_registry = {
            "task1": EasyDBOverloadTask,
            "task2": MediumMemoryLeakTask,
            "task3": HardFeedbackLoopTask
        }
        

    def reset(self, taskId="task1"):
        """Initialize environment with DB overload scenario (easy task)."""
        self._state = State(episode_id=str(uuid4()), step_count=0)

        self.task = self.task_registry.get(taskId)()
        if self.task is None:
            raise ValueError("Given Task Id is not present in the registory")
        

        self._internal_state = self.task.get_initial_state()
        self.actions = []

        return self._get_observation()


    def _get_observation(self):
        s = self._internal_state["services"]

        logs, alerts = self.task.get_additional_observations(s, self._state.step_count)

        metrics = {
            "api_latency": s["api"]["latency"] + random.randint(-10, 10),
            "api_error": s["api"]["error"],
            "api_free_memory": s["api"]["free_memory"],
            "db_cpu": s["db"]["cpu"],
            "db_connections": s["db"]["connections"],
            "db_latency": s["db"]["latency"] + random.randint(-10, 10),
            "db_disk_availability": s["db"]["disk_available"],
            "task_runner_cpu": s["task_runner"]["cpu"],
            "task_runner_disk": s["task_runner"]["disk_available"],
            "task_runner_free_memory": s["task_runner"]["free_memory"]
        }

        if s["db"]["connections"] > 90:
            logs.append("DB connection pool exhausted")

        if s["api"]["latency"] > 500:
            logs.append("High API latency detected")

        if s["task_runner"]["latency"] > 500:
            logs.append("High latency detected for task runner pods")


        if metrics["api_latency"] > 500:
            alerts.append("High latency alert")
        if metrics["db_cpu"] > 75:
            alerts.append("High CPU usage in db")
        if metrics["db_latency"] > 500:
            alerts.append("High DB Latency alert")
        if metrics["db_disk_availability"] < 50:
            alerts.append("db_disk_availability is under 50 GB")
        if metrics["task_runner_free_memory"] < 2: # less than 2GB free free_memory left
            alerts.append("task runner free_memory hitting limit")
        if metrics["api_free_memory"] < 2:
            alerts.append("api server free_memory hitting limit")
        if metrics["task_runner_disk"] < 10:
            alerts.append("task_runner_disk availability is under 50 GB")

        return DeployBuddyObservation(
            metrics=metrics,
            logs=logs,
            alerts=alerts,
            step=self._state.step_count,
            done=False,
            reward=0.0,
            metadata={},
        )


    def _apply_action(self, action: DeployBuddyAction):
        self.task.apply_actions(self._internal_state["services"], action)

    def _simulate(self):
        s = self._internal_state["services"]

        # DB overload impacts API
        if s["db"]["cpu"] > 85:
            s["db"]["latency"] += 20
            s["api"]["latency"] += 15
            s["api"]["error"] += 0.05

        # natural recovery
        s["api"]["latency"] *= 0.95
        s["api"]["error"] *= 0.95

    def _compute_reward(self, prev_state, curr_state, action):
        return self.task.compute_reward(prev_state, curr_state, action)

    # def _is_resolved(self, observations: DeployBuddyObservation):
    #     alerts = len(observations.alerts)
    #     # resolved if there are no alerts left
    #     if alerts == 0:
    #         return True
    #     return False
    
    def grade(self):
        return self.task.grade(
            self._internal_state,
            self.actions
        )

    def evaluate(self):
        return self.grade()

    def step(self, action: DeployBuddyAction) -> DeployBuddyObservation:
        prev_state = deepcopy(self._internal_state)

        self._state.step_count += 1
        self._internal_state["time"] += 1

        self.actions.append(action)

        # apply action
        self._apply_action(action)

        # simulate environment
        self._simulate()

        # compute reward
        reward = self._compute_reward(prev_state, self._internal_state, action)

        

        obs = self._get_observation()

        # check termination
        done = self._is_resolved(obs)
        obs.reward = reward
        obs.done = done

        if done:
            obs.reward = 1

        return obs
    
    def _is_resolved(self, observations):
        success = self.task.grade(self._internal_state, self.actions)["success"]
        return success

    @property
    def state(self) -> State:
        return self._state