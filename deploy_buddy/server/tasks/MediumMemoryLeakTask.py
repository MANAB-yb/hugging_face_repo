from deploy_buddy.models import DeployBuddyAction


class MediumMemoryLeakTask:
    def __init__(self):
        self.name = "medium"
        self.MAX_REPLICAS = 6

    def get_initial_state(self):
        return {
            "services": {
                "api": {"latency": 300, "error": 0.4, "replicas": 2, "cpu": 65, "connections": 50, "free_memory": 12, "disk_available": 50},
                "task_runner": {"latency": 200, "error": 1, "free_memory": 0.5, "replicas": 1, "cpu": 85, "connections": 90, "disk_available": 12},
                "db": {"cpu": 60, "connections": 70, "replicas": 1, "latency": 50, "disk_available": 70, "free_memory": 12},
            },
            "incident": "memory_leak",
            "time": 0,
        }
    
    def get_additional_observations(self, internal_state, calls):
        alerts = []
        init_logs = [
            "api server polling for edit universe abc succeeded current state editing",
            "api server polling for edit universe abc succeeded current state editing",
            "api server polling for edit universe abc succeeded current state edited",
            "upgraded version of task_runner from v1 to v2"
            ]
        kube_restart_logs = [
                "memory of task runner is hiting the limit recreating the pods ...",
                "memory of task runner is hiting the limit recreating the pods ...",
                "memory of task runner is hiting the limit recreating the pods ...",
                "api server polling for task create universe def failed due to connectivity failure",
                "memory of task runner is hiting the limit recreating the pods ...",
                "memory of task runner is hiting the limit recreating the pods ...",
                "api server polling for task create universe def failed due to connectivity failure",
                "memory of task runner is hiting the limit recreating the pods ...",
                "api server submitting task for create universe failed ... no response from task runner"
            ]
        logs = []
        if calls == 0:
            return init_logs + kube_restart_logs, alerts
        elif internal_state["task_runner"]["free_memory"] < 1.0:
            # Still memory is leaking so pods are continiously getting restart
            return kube_restart_logs, alerts
        else:
            # if more than 1 GB free memory left then we can say it's stable
            return [], alerts
    
        


    def apply_actions(self, internal_state, action: DeployBuddyAction):
        if action.action_type == "scale_service":
            svc = action.target
            delta = action.value
            if delta == 0:
                return internal_state # nothing to increase if 0
            
            if svc == "db":
                curr_replicas = internal_state["db"]["replicas"]
                final_count = min(curr_replicas + delta, self.MAX_REPLICAS)
                # as of now evenly distributing the total load accross the instances
                internal_state["db"]["cpu"] = max(((internal_state["db"]["cpu"] * curr_replicas) / final_count), 20)
                internal_state["db"]["connections"] = max(((internal_state["db"]["connections"] * curr_replicas) / final_count), 2)
                internal_state["db"]["latency"] = max(((internal_state["db"]["latency"] * curr_replicas) / final_count), 2)
                internal_state["db"]["replicas"] = final_count
            elif svc == "api":
                curr_replicas = internal_state["api"]["replicas"]
                final_count = min(curr_replicas + delta, self.MAX_REPLICAS)
                # as of now evenly distributing the total load accross the instances
                internal_state["api"]["cpu"] = max(((internal_state["api"]["cpu"] * curr_replicas) / final_count), 20)
                internal_state["api"]["connections"] = max(((internal_state["api"]["connections"] * curr_replicas) / final_count), 2)
                internal_state["api"]["replicas"] = final_count
                # Will add some internal load on the DB
                internal_state["db"]["cpu"] = min(internal_state["db"]["cpu"] + 5, 100)
                added_replica = action.value
                # internal_state["api"]["free_memory"] = min((internal_state["api"]["free_memory"] + added_replica * 5), 15)
                # adds lot of loads to task runner as more pods will request task runner
                internal_state["task_runner"]["free_memory"] = max(internal_state["task_runner"]["free_memory"] - 0.3 * final_count, 0.0)
            else:
                # Task Runner
                curr_replicas = internal_state["task_runner"]["replicas"]
                final_count = min(curr_replicas + delta, self.MAX_REPLICAS)
                # task runner is leaking a high amount of memory more than what allocated
                # due to buggy code so new pods will also have utilize the memory and cpu allocated to it or may be less
                # so decreasing memory very less when new instance added and will increase penalty for that action
                internal_state["task_runner"]["cpu"] = min(internal_state["task_runner"]["cpu"] + 2, 100)
                internal_state["task_runner"]["connections"] = max(((internal_state["task_runner"]["connections"] * curr_replicas) / final_count), 2)
                internal_state["task_runner"]["replicas"] = final_count
                internal_state["task_runner"]["free_memory"] = max(internal_state["task_runner"]["free_memory"] - 0.1 * delta, 0.1)
                # Will add some internal load on the DB
                internal_state["db"]["cpu"] = min(internal_state["db"]["cpu"] + 5, 100)

        elif action.action_type == "revert_version":
            svc = action.target
            # Reverting db and api versions have no impact
            if svc == "task_runner":
                internal_state["task_runner"]["free_memory"] = 7
                internal_state["task_runner"]["cpu"] = 60
                internal_state["task_runner"]["error"] = 0.1
                internal_state["task_runner"]["latency"] = 100
                return internal_state
        # Memory leaks after every step
        internal_state["task_runner"]["free_memory"] = max(internal_state["task_runner"]["free_memory"] - 0.2, 0)
        if internal_state["task_runner"]["free_memory"] < 1:
            internal_state["task_runner"]["latency"] += 20
            internal_state["api"]["latency"] += 10
        
        # In all other tasks it can improve a bit for some time but ultimately will come to the same state
        return internal_state
    
    def compute_reward(self, prev_state, curr_state, action: DeployBuddyAction):
        reward = 0.0

        curr_api = curr_state["services"]["api"]

        curr_db = curr_state["services"]["db"]

        prev_task_runner = prev_state["services"]["task_runner"]
        curr_task_runner = curr_state["services"]["task_runner"]

        reward += (prev_task_runner["latency"] - curr_task_runner["latency"]) * 0.01
        reward += (prev_task_runner["cpu"] - curr_task_runner["cpu"]) * 0.01
        reward += (curr_task_runner["free_memory"] - prev_task_runner["free_memory"]) * 0.01

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
        penalty += under_util_penalty(curr_task_runner["cpu"], curr_task_runner["free_memory"])

        reward -= penalty

        # penalize for each node increase to maintain cost
        if action.action_type == "revert_version" and action.target == "task_runner":
            reward += 2.0
        elif action.action_type == "scale_service":
            reward -= 0.1 * action.value
        else:
            # penalizing for each incorrect action
            reward -= 0.1
        
        return reward
    
    def grade(self, final_state, actions):
        tr = final_state["services"]["task_runner"]

        reverted = any(
            a.action_type == "revert_version" and a.target == "task_runner"
            for a in actions
        )

        memory_ok = tr["free_memory"] > 2

        success = reverted and memory_ok
        score = 0.0
        if reverted and not memory_ok:
            score = 0.4
        if success:
            score = 1.0

        return {
            "success": success,
            "score": score,
            "reason": (
                "Memory leak fixed via revert"
                if success else
                "Memory leak not properly resolved"
            )
        }