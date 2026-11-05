"""Evaluations of the AI agents: for each, a dataset of cases with checked answers, a runner
that calls the agent's real entry point on each, and graders (evals/framework.py). See
docs/evals.md."""


def registry() -> dict:
    """{eval name: its Spec}, in the order the dashboard lists them."""
    from stock_news_analyzer.evals import events, results

    return {spec.name: spec for spec in (events.SPEC, results.SPEC)}
