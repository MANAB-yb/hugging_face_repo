from deploy_buddy.models import DeployBuddyAction


class HardFeedbackLoopTask:
    def __init__(self):
        self.name = "hard"
        self.MAX_REPLICAS = 8

    def get_initial_state(self):
        return {
            "services": {
                "api": {
                    "latency": 280,
                    "error": 0.3,
                    "replicas": 3,
                    "cpu": 84,
                    "connections": 120,
                    "free_memory": 4,
                    "disk_available": 50
                },
                "task_runner": {
                    "latency": 250,
                    "error": 0.2,
                    "free_memory": 1,
                    "replicas": 2,
                    "cpu": 80,
                    "connections": 80,
                    "disk_available": 50
                },
                "db": {
                    "cpu": 70,
                    "connections": 110,
                    "replicas": 1,
                    "latency": 300,
                    "disk_available": 50,
                    "free_memory": 8
                },
            },
            "incident": "feedback_loop",
            "time": 0,
        }

    def get_additional_observations(self, internal_state, calls):
        logs = []
        alerts = []

        retry_logs = [
            "Task Runner request rate spike detected ...",
            "Task Runner request rate spike detected ...",
            "Task Runner request rate spike detected ...",
            "Latency in Task runner response increasing",
            "API Server: poling for task create cluster failed, due to connection reset by peers",
            "API Server: poling for task create cluster failed, due to connection reset by peers",
            "API Server: poling for task create cluster failed, due to connection reset by peers",
            "API Server: Scheduling task for edit cluster failed, timeout peer did not respond in time",
            # "message queue for task runner"
            "TASK RUNNER Cpu hitting the limit ...",
            "API SERVER CPU hitting limit"
        ]

        if calls == 0:
            logs.extend([
                "spike in incoming traffic to the components detected",
                "spike in requests: task runner detected",
                "Task Runner CPU throttling",
                "Latency in Task runner response detected",
                "api latency increasing gradually",
                "db cpu usage increasing"
            ])
            logs.extend(retry_logs)
        elif internal_state["task_runner"]["cpu"] > 70:
            logs.extend(retry_logs)

        return logs, alerts

    def apply_actions(self, internal_state, action: DeployBuddyAction):
        if action.action_type == "scale_service":
            svc = action.target
            delta = action.value
            if delta == 0:
                return internal_state

            # ---------- DB ----------
            if svc == "db":
                curr = internal_state["db"]["replicas"]
                new = min(curr + delta, self.MAX_REPLICAS)

                internal_state["db"]["cpu"] = max(
                    (internal_state["db"]["cpu"] * curr) / new, 30
                )
                internal_state["db"]["connections"] = max(
                    (internal_state["db"]["connections"] * curr) / new, 10
                )
                internal_state["db"]["latency"] = max(
                    (internal_state["db"]["latency"] * curr) / new, 50
                )
                internal_state["db"]["replicas"] = new

            # ---------- API ----------
            elif svc == "api":
                curr = internal_state["api"]["replicas"]
                new = min(curr + delta, self.MAX_REPLICAS)

                # Api Server Continiously trying to query task runner for tasks statuses, so more threads are being acquired
                internal_state["api"]["cpu"] = min(
                    internal_state["api"]["cpu"] + 2 * delta, 100
                )
                internal_state["api"]["connections"] += 3 * delta
                internal_state["api"]["replicas"] = new

            # ---------- TASK RUNNER ----------
            else:
                curr = internal_state["task_runner"]["replicas"]
                new = min(curr + delta, self.MAX_REPLICAS)

                internal_state["task_runner"]["cpu"] = min(
                    internal_state["task_runner"]["cpu"] - 3 * delta, 100
                )
                internal_state["task_runner"]["connections"] = (internal_state["db"]["connections"] * curr) / new
                internal_state["task_runner"]["latency"] = max((internal_state["api"]["latency"] * curr) / new, 100)
                internal_state["task_runner"]["replicas"] = new

                # Cascading effect on API Server & DB load reduces
                internal_state["db"]["cpu"] = max(
                    internal_state["db"]["cpu"] - 4 * delta, 20
                )
                
                internal_state["db"]["latency"] = max((internal_state["db"]["latency"] * curr) / new, 100)

                internal_state["api"]["cpu"] = max(
                    internal_state["api"]["cpu"] - 4 * delta, 20
                )
                
                internal_state["api"]["latency"] = max((internal_state["api"]["latency"] * curr) / new, 100)

        elif action.action_type == "scale_down_service":
            svc = action.target
            delta = action.value

            if delta == 0:
                return internal_state

            # ---------- DB ----------
            if svc == "db":
                curr = internal_state["db"]["replicas"]
                new = max(curr - delta, 1)

                # redistribute load (fewer nodes → more pressure)
                internal_state["db"]["cpu"] = min(
                    (internal_state["db"]["cpu"] * curr) / new, 100
                )
                internal_state["db"]["connections"] = min(
                    (internal_state["db"]["connections"] * curr) / new, 200
                )
                internal_state["db"]["latency"] = min(
                    (internal_state["db"]["latency"] * curr) / new, 1000
                )
                internal_state["db"]["replicas"] = new

            # ---------- API ----------
            elif svc == "api":
                curr = internal_state["api"]["replicas"]
                new = max(curr - delta, 1)

                internal_state["api"]["cpu"] = min(
                    (internal_state["api"]["cpu"] * curr) / new, 100
                )
                internal_state["api"]["connections"] = min(
                    (internal_state["api"]["connections"] * curr) / new, 200
                )
                internal_state["api"]["latency"] = min(
                    (internal_state["api"]["latency"] * curr) / new, 1000
                )
                internal_state["api"]["replicas"] = new

            # ---------- TASK RUNNER ----------
            else:
                curr = internal_state["task_runner"]["replicas"]
                new = max(curr - delta, 1)

                internal_state["task_runner"]["cpu"] = min(
                    internal_state["task_runner"]["cpu"] + 5 * delta, 100
                )
                internal_state["task_runner"]["replicas"] = new

                # reducing task runner reduces pressure on DB slightly
                internal_state["db"]["cpu"] = max(
                    internal_state["db"]["cpu"] - 2 * delta, 20
                )


        elif action.action_type == "restart_service":
            svc = action.target

            if svc == "api":
                # reduces retry storm
                internal_state["api"]["error"] = 0.1
                internal_state["api"]["connections"] = max(
                    internal_state["api"]["connections"] - 90, 20
                )
                internal_state["api"]["latency"] = max(
                    internal_state["api"]["latency"] - 150, 100
                )

        return internal_state

    def compute_reward(self, prev_state, curr_state, action: DeployBuddyAction):
        reward = 0.0

        prev_api = prev_state["services"]["api"]
        curr_api = curr_state["services"]["api"]

        prev_db = prev_state["services"]["db"]
        curr_db = curr_state["services"]["db"]
        
        prev_task = prev_state["services"]["task_runner"]
        curr_task = curr_state["services"]["task_runner"]

        reward += (prev_api["latency"] - curr_api["latency"]) * 0.01
        reward += (prev_db["cpu"] - curr_db["cpu"]) * 0.01
        reward += (prev_db["latency"] - curr_db["latency"]) * 0.01

        if action.action_type == "scale_service":
            reward -= 0.1 * action.value

        if action.action_type == "scale_down_service":
            # check if the action is incorrect penalize hard
            if action.target == "api":
                if action.value >= prev_api["replicas"]:
                    return -1 # At least 1 replica should be running always
            elif action.target == "db":
                if action.value >= prev_db["replicas"]:
                    return -1
            elif action.value == "task_runner":
                if action.value >= prev_task["replicas"]:
                    return -1
            else:
                return -1 # no matching components
            reward -= 0.05 * action.value  # smaller penalty (encourage fixing over-provisioning)

        if action.action_type == "restart_service" and action.target == "api":
            reward += 2.5

        if curr_db["cpu"] > prev_db["cpu"]:
            reward -= 0.2

        # penalty for underutilized resources we want to be cost efficient
        def under_util_penalty(cpu, free_mem):
            penalty = 0.0
            if free_mem < 16 or cpu > 30:
                return penalty # only penalize if everything is underutilized
            if free_mem >= 16:
                penalty += (free_mem - 16) * 0.03 
            if cpu <= 30:
                penalty += (30 - cpu) * 0.03
            return penalty

        penalty = 0.0
        penalty += under_util_penalty(curr_api["cpu"], curr_api["free_memory"])
        penalty += under_util_penalty(curr_db["cpu"], curr_db["free_memory"])
        penalty += under_util_penalty(curr_task["cpu"], curr_task["free_memory"])

        reward -= penalty

        return reward
    
    def grade(self, final_state, actions):
        api = final_state["services"]["api"]
        db = final_state["services"]["db"]
        task = final_state["services"]["task_runner"]

        restarted_api = any(
            a.action_type == "restart_service" and a.target == "api"
            for a in actions
        )

        api_ok = api["latency"] < 200 and api["error"] < 0.15
        db_ok = db["cpu"] < 70 and db["latency"] < 200
        task_ok = task["latency"] < 300 and task["cpu"] < 70 and task["free_memory"] > 3

        success = api_ok and db_ok and task_ok
        score = 0.0
        if task_ok:
            score += 0.3
        if db_ok:
            score += 0.3
        if api_ok:
            score += 0.4

        return {
            "success": success,
            "score": 1.0 if success else 0.0,
            "reason": (
                "Feedback loop resolved correctly"
                if success else
                "Incorrect mitigation or root cause not addressed"
            )
        }