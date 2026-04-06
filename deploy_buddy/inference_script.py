import asyncio
import os
import json
from typing import List, Optional

from openai import OpenAI
from deploy_buddy import DeployBuddyAction, DeployBuddyEnv


# ---------- ENV CONFIG ----------
IMAGE_NAME = os.getenv("IMAGE_NAME")
API_KEY = os.getenv("HF_TOKEN") or os.getenv("API_KEY")

API_BASE_URL = "https://router.huggingface.co/v1"
# MODEL_NAME = os.getenv("MODEL_NAME") or "Qwen/Qwen2.5-72B-Instruct"
MODEL_NAME = "deepseek-ai/DeepSeek-R1"

# TASKS = ["task1", "task2", "task3"]
TASKS = ["task3"]
BENCHMARK = "deploy_buddy"

MAX_STEPS = 10
TEMPERATURE = 0.3
MAX_TOKENS = 200


# ---------- SYSTEM PROMPT ----------
SYSTEM_PROMPT = """
You are an SRE agent responsible for diagnosing and fixing production incidents.

You will receive:
- metrics (numerical signals)
- logs (system behavior hints)
- alerts (symptoms)

Your job is to:
1. Carefully analyze ALL signals
2. Identify the MOST LIKELY root cause
3. Take ONE action that directly addresses the root cause

Guidelines:
- DO NOT blindly scale services
- Scaling is useful only if the issue is resource saturation
- Logs often contain the real root cause — prioritize them
- Repeated failures or restarts indicate deeper issues (not scaling problems)
- If a recent change caused instability, consider reverting it
- Avoid unnecessary actions — efficiency matters

Valid actions STRICTLY MAINTAIN THIS LIST:
1. scale_service(target=<api|db|task_runner>, value=<int>)
2. scale_down_service(target=<api|db|task_runner>, value=<int>)
3. restart_service(target=<api|db|task_runner>)
4. revert_version(target=<api|db|task_runner>)
5. wait

Scaling can be an INCORRECT action.

If the issue is caused by:
- memory leaks
- version bugs
- repeated restarts
- failing dependencies

Then scaling WILL NOT fix the problem and should be avoided.

If you scale without strong evidence of resource saturation,
you are likely making the system worse.

In distributed systems, issues can propagate across services.

A symptom in one service does NOT always mean that service is the root cause.

Before taking action:
- Identify which component is the SOURCE of the issue
- Distinguish between root cause vs downstream impact

Examples:
- High API latency may be caused by DB overload
- Task failures may be caused by memory issues in task_runner

Always act on the ROOT CAUSE component, not the symptom.

Reverting a version is a high-impact action and should NOT be used blindly.

Only use revert_version if there is clear evidence of a recent change causing instability.

Evidence may include:
- logs mentioning upgrades, deployments, or version changes
- errors starting after a change event
- repeated failures following a version update

If there is NO indication of a recent change, avoid reverting.

Unnecessary reverts can disrupt a stable system and should be avoided.

Output STRICTLY JSON:
{
  "action_type": "...",
  "target": "...",
  "value": <int or null>
}
DO NOT include any explanation. ONLY output valid JSON.
If your output is not valid JSON, your answer is considered WRONG.
"""


# ---------- LOGGING ----------
def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)

import re
import json

def extract_json(text: str):
    try:
        # direct parse
        return json.loads(text)
    except:
        pass

    # try to extract JSON block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass

    return None

def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(f"[STEP] step={step} action={action} reward={reward:.2f} done={done_val} error={error_val}", flush=True)


def log_end(success: bool, steps: int, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(f"[END] success={str(success).lower()} steps={steps} rewards={rewards_str}", flush=True)


# ---------- PROMPT ----------
def build_prompt(obs, history) -> str:
    history_block = "\n".join(history[-3:]) if history else "None"

    return f"""
=== OBSERVATION ===

Metrics:
{json.dumps(obs.metrics, indent=2)}

Alerts:
{obs.alerts}

Logs (most recent last):
{obs.logs[-8:]}

Previous Actions:
{history_block}

===================

What is the SINGLE best action to fix the system?

Remember:
- Identify root cause
- Avoid unnecessary scaling
- Prefer precise fixes over brute force
"""


# ---------- MODEL ----------
def get_action(client: OpenAI, obs, history):
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(obs, history)},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )

        text = completion.choices[0].message.content.strip()

        action_dict = extract_json(text)

        if action_dict is None:
            raise ValueError("Invalid JSON")

        return DeployBuddyAction(**action_dict), text

    except Exception as e:
        print(f"[DEBUG] Model error: {e}", flush=True)

        # Neutral fallback (NOT scaling biased)
        return DeployBuddyAction(
            action_type="restart_service",
            target="api",
            value=None
        ), "fallback_action"


# ---------- MAIN ----------
async def main():
    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

    env = await DeployBuddyEnv.from_docker_image(IMAGE_NAME)

    try:
        for task in TASKS:
            rewards: List[float] = []
            history: List[str] = []
            steps_taken = 0
            success = False

            log_start(task=task, env=BENCHMARK, model=MODEL_NAME)

            try:
                result = await env.reset(taskId=task)

                for step in range(1, MAX_STEPS + 1):
                    obs = result.observation

                    action, action_str = get_action(client, obs, history)

                    result = await env.step(action)

                    reward = result.reward or 0.0
                    done = result.done

                    rewards.append(reward)
                    steps_taken = step

                    log_step(step, action_str, reward, done, None)

                    history.append(f"Step {step}: {action_str} -> {reward:.2f}")

                    if done:
                        success = True
                        break

                # if not solved explicitly
                if not success:
                    success = result.done

            finally:
                log_end(success=success, steps=steps_taken, rewards=rewards)

    finally:
        try:
            await env.close()
        except Exception as e:
            print(f"[DEBUG] env.close error: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())