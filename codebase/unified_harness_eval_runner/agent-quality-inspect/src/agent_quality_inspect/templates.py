DEFAULT_MODEL_GRADED_FACT_DYNAMIC_SUMMARY_NO_STEPS_REMOVE_HALLUCINATION_CHECK_TEMPLATE_ONE_SUBGOAL = """
You are provided with a sample that contains several key components centered around an interaction between an agent and a simulated user, referred to as the user proxy. The user proxy represents a human-in-the-loop, engaging with the agent by posing questions and guiding the conversation throughout the dialogue.

The [User Summary Instructions] section outlines the user's goals, expectations, and the overall task the agent is expected to complete. The [Agent Responses Submission] section captures the agent's actual responses to the user proxy at each turn of the interaction. The [Agent Intermediate Trajectories] section provides a detailed step-by-step reasoning and actions taken by the agent. Finally, the [Dynamic Dialogue] section presents the full conversation between the agent and the user proxy.

As a judge, your task is to determine whether the subgoal specified in the [Ground Truth Subgoal] has been achieved. To make this assessment, evaluate the [Agent Intermediate Trajectories] and [Agent Responses Submission] to ascertain whether the subgoal has been successfully completed.

Do NOT attempt to infer or reconcile differences between values when they are clearly different or potentially contain typographical errors. This rule does not apply to values that are effectively the same: a numeric value that matches the target to the nearest whole currency unit MUST be treated as equivalent. Sub-unit or cents-level differences (for example, 12,922,923.98 vs 12,922,924), floating-point residue, and differences in thousands separators, decimal separators, or other number formatting all represent the SAME value and MUST be graded COMPLETE. The same applies to values represented in another form that is still semantically equivalent (e.g., different number formats or naming conventions that retain the same meaning). Only genuinely different magnitudes — differences larger than such rounding/formatting effects — count as clearly different and remain INCOMPLETE.

[BEGIN DATA]
************
[User Summary Instructions]:
{userTask}

************
[Ground Truth Subgoal]:
{subgoal}

************
[Agent Intermediate Trajectories]:
{trajectories}

************
[Agent Responses Submission]:
{answers}

************
[Dynamic Dialogue]:
{dynamicDialogue}
[END DATA]

During assessment focus solely on the factual content and the goal completion while disregarding any differences in style, grammar, punctuation, or syntax.

Begin by presenting a concise argument to confirm the validity of your conclusion. Avoid simply stating the correct answers at the outset. End with your answer formatted as 'GRADE: $LETTER' (without quotes) where LETTER is one of C or I. Reply with 'GRADE: C' (without quotes) to indicate COMPLETE if the agent has successfully achieved the subgoal. Otherwise, reply with 'GRADE: I' (without quotes) to indicate INCOMPLETE if the agent did not achieved the subgoal.
"""
