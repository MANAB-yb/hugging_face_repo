from deploy_buddy.models import DeployBuddyAction


class HardFeedbackLoopTask:
    def __init__(self):
        self.name = "hard"
        self.MAX_REPLICAS = 8

    def get_initial_state(self):
        return {
            "services": {
                "api": {
                    "latency": 400,
                    "error": 0.3,
                    "replicas": 3,
                    "cpu": 75,
                    "connections": 120,
                    "free_memory": 4
                },
                "task_runner": {
                    "latency": 250,
                    "error": 0.2,
                    "free_memory": 3,
                    "replicas": 2,
                    "cpu": 70,
                    "connections": 80,
                    "disk_available": 20
                },
                "db": {
                    "cpu": 85,
                    "connections": 110,
                    "replicas": 1,
                    "latency": 300
                },
            },
            "incident": "feedback_loop",
            "time": 0,
        }

    def get_additional_observations(self, internal_state, calls):
        logs = []
        alerts = []

        retry_logs = [
            "api retrying failed request to db...",
            "api retrying failed request to db...",
            "increased retry attempts detected in api layer",
            "db responding slowly, queries timing out",
            "retry storm detected between api and db"
        ]

        if calls == 0:
            logs.extend([
                "spike in incoming traffic detected",
                "api latency increasing gradually",
                "db cpu usage increasing"
            ])
            logs.extend(retry_logs)
        elif internal_state["api"]["error"] > 0.25:
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

                internal_state["api"]["cpu"] = min(
                    internal_state["api"]["cpu"] + 5 * delta, 100
                )
                internal_state["api"]["connections"] += 30 * delta
                internal_state["api"]["replicas"] = new

                # 🔥 FEEDBACK LOOP TRIGGER
                internal_state["db"]["cpu"] = min(
                    internal_state["db"]["cpu"] + 10 * delta, 100
                )
                internal_state["db"]["connections"] += 40 * delta
                internal_state["db"]["latency"] += 20 * delta

            # ---------- TASK RUNNER ----------
            else:
                curr = internal_state["task_runner"]["replicas"]
                new = min(curr + delta, self.MAX_REPLICAS)

                internal_state["task_runner"]["cpu"] = min(
                    internal_state["task_runner"]["cpu"] + 3 * delta, 100
                )
                internal_state["task_runner"]["replicas"] = new

        elif action.action_type == "restart_service":
            svc = action.target

            if svc == "api":
                # ✅ correct action: reduces retry storm
                internal_state["api"]["error"] = 0.1
                internal_state["api"]["connections"] = max(
                    internal_state["api"]["connections"] - 50, 20
                )
                internal_state["api"]["latency"] = max(
                    internal_state["api"]["latency"] - 100, 100
                )

        return internal_state

    def compute_reward(self, prev_state, curr_state, action: DeployBuddyAction):
        reward = 0.0

        prev_api = prev_state["services"]["api"]
        curr_api = curr_state["services"]["api"]

        prev_db = prev_state["services"]["db"]
        curr_db = curr_state["services"]["db"]

        # reward improvements
        reward += (prev_api["latency"] - curr_api["latency"]) * 0.01
        reward += (prev_db["cpu"] - curr_db["cpu"]) * 0.01
        reward += (prev_db["latency"] - curr_db["latency"]) * 0.01

        # penalize scaling (cost)
        if action.action_type == "scale_service":
            reward -= 0.1 * action.value

        # reward correct fix
        if action.action_type == "restart_service" and action.target == "api":
            reward += 2.5

        # penalize making feedback loop worse
        if curr_db["cpu"] > prev_db["cpu"]:
            reward -= 0.2

        return min(max(reward, -1.0), 1.0)
    
    def grade(self, final_state, actions):
        api = final_state["services"]["api"]
        db = final_state["services"]["db"]

        restarted_api = any(
            a.action_type == "restart_service" and a.target == "api"
            for a in actions
        )

        api_ok = api["latency"] < 200 and api["error"] < 0.15
        db_ok = db["cpu"] < 70 and db["latency"] < 200

        success = restarted_api and api_ok and db_ok

        return {
            "success": success,
            "score": 1.0 if success else 0.0,
            "reason": (
                "Feedback loop resolved correctly"
                if success else
                "Incorrect mitigation or root cause not addressed"
            )
        }