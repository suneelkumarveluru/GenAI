"""ROI framework for an agentic AI use case.

The model is deliberately simple and transparent. For every month of the horizon:

    benefits  = labor saved on tasks the agent completes end to end
              + labor saved on tasks where the agent drafts and a human reviews
              + value of fewer errors (can be negative if the agent errs more)
              + any other monthly benefit you can defend (revenue uplift, SLA credits avoided)
    run costs = LLM / token cost for every task routed to the agent
              + rework on agent mistakes
              + infrastructure + maintenance (people who keep the agent healthy)
    build     = one-time cost in month 0

Adoption ramps linearly from 0 to 100% over ``ramp_months``.

Outputs: NPV, ROI %, payback month, steady-state economics, break-even automation rate,
a sensitivity ("tornado") table and pessimistic / base / optimistic scenarios.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any


@dataclass
class UseCase:
    name: str
    tasks_per_month: float
    minutes_per_task_manual: float
    loaded_hourly_cost: float
    automation_rate: float

    description: str = ""

    # Share of tasks where the agent drafts and a human reviews (saves part of the time).
    assist_rate: float = 0.0
    assist_time_saving: float = 0.4

    # Quality
    error_rate_manual: float = 0.0
    error_rate_agent: float = 0.0
    cost_per_error: float = 0.0
    rework_minutes: float = 10.0

    # Running costs
    llm_cost_per_task: float = 0.0
    infra_cost_per_month: float = 0.0
    maintenance_fte: float = 0.0
    fte_annual_cost: float = 150_000.0

    # One-time + timing
    build_cost: float = 0.0
    ramp_months: int = 6
    horizon_months: int = 36
    discount_rate_annual: float = 0.10

    other_monthly_benefit: float = 0.0

    # ------------------------------------------------------------------ helpers
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UseCase":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown use-case fields: {sorted(unknown)}")
        uc = cls(**data)
        uc.validate()
        return uc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        for name in ("automation_rate", "assist_rate", "assist_time_saving", "error_rate_manual", "error_rate_agent"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1, got {value}")
        if self.automation_rate + self.assist_rate > 1.0 + 1e-9:
            raise ValueError("automation_rate + assist_rate cannot exceed 1")
        for name in (
            "tasks_per_month",
            "minutes_per_task_manual",
            "loaded_hourly_cost",
            "cost_per_error",
            "rework_minutes",
            "llm_cost_per_task",
            "infra_cost_per_month",
            "maintenance_fte",
            "fte_annual_cost",
            "build_cost",
            "other_monthly_benefit",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.horizon_months < 1:
            raise ValueError("horizon_months must be at least 1")
        if self.ramp_months < 0:
            raise ValueError("ramp_months cannot be negative")
        if self.discount_rate_annual <= -1:
            raise ValueError("discount_rate_annual must be greater than -1")

    @property
    def manual_cost_per_task(self) -> float:
        return self.minutes_per_task_manual / 60.0 * self.loaded_hourly_cost


@dataclass
class ROIResult:
    use_case: str
    horizon_months: int
    cash_flows: list[float]  # index 0 = build cost (negative), 1..H = monthly net
    total_benefits: float
    total_run_costs: float
    build_cost: float
    net_value: float
    roi_pct: float | None
    npv: float
    payback_month: int | None
    steady_state_benefit: float
    steady_state_run_cost: float
    steady_state_net: float
    manual_cost_per_task: float
    agent_cost_per_task: float  # steady-state run cost spread over all tasks routed to the agent
    break_even_automation_rate: float | None = None
    breakdown: dict[str, float] = field(default_factory=dict)


# --------------------------------------------------------------------------- core


def _adoption(month: int, ramp_months: int) -> float:
    if ramp_months <= 0:
        return 1.0
    return min(1.0, month / ramp_months)


def _month(uc: UseCase, adoption: float) -> dict[str, float]:
    tasks = uc.tasks_per_month * adoption
    manual = uc.manual_cost_per_task
    hourly = uc.loaded_hourly_cost

    labor_automated = tasks * uc.automation_rate * manual
    labor_assisted = tasks * uc.assist_rate * manual * uc.assist_time_saving
    quality = tasks * uc.automation_rate * (uc.error_rate_manual - uc.error_rate_agent) * uc.cost_per_error
    other = uc.other_monthly_benefit * adoption

    llm = tasks * uc.llm_cost_per_task
    rework = tasks * uc.automation_rate * uc.error_rate_agent * uc.rework_minutes / 60.0 * hourly
    infra = uc.infra_cost_per_month
    maintenance = uc.maintenance_fte * uc.fte_annual_cost / 12.0

    benefits = labor_automated + labor_assisted + quality + other
    run_costs = llm + rework + infra + maintenance
    return {
        "labor_automated": labor_automated,
        "labor_assisted": labor_assisted,
        "quality": quality,
        "other": other,
        "llm": llm,
        "rework": rework,
        "infra": infra,
        "maintenance": maintenance,
        "benefits": benefits,
        "run_costs": run_costs,
        "net": benefits - run_costs,
    }


def _npv(cash_flows: list[float], annual_rate: float) -> float:
    monthly = (1.0 + annual_rate) ** (1.0 / 12.0) - 1.0
    return sum(cf / (1.0 + monthly) ** m for m, cf in enumerate(cash_flows))


def calculate(uc: UseCase, with_break_even: bool = True) -> ROIResult:
    """Run the model for one use case."""
    uc.validate()
    cash_flows = [-uc.build_cost]
    totals: dict[str, float] = {}
    total_benefits = total_run = 0.0
    for m in range(1, uc.horizon_months + 1):
        flow = _month(uc, _adoption(m, uc.ramp_months))
        cash_flows.append(flow["net"])
        total_benefits += flow["benefits"]
        total_run += flow["run_costs"]
        for key, value in flow.items():
            totals[key] = totals.get(key, 0.0) + value

    cumulative, payback = -uc.build_cost, None
    if cumulative >= 0:
        payback = 0
    else:
        for m in range(1, uc.horizon_months + 1):
            cumulative += cash_flows[m]
            if cumulative >= 0:
                payback = m
                break

    steady = _month(uc, 1.0)
    total_cost = uc.build_cost + total_run
    net_value = total_benefits - total_cost
    result = ROIResult(
        use_case=uc.name,
        horizon_months=uc.horizon_months,
        cash_flows=cash_flows,
        total_benefits=total_benefits,
        total_run_costs=total_run,
        build_cost=uc.build_cost,
        net_value=net_value,
        roi_pct=(net_value / total_cost * 100.0) if total_cost > 0 else None,
        npv=_npv(cash_flows, uc.discount_rate_annual),
        payback_month=payback,
        steady_state_benefit=steady["benefits"],
        steady_state_run_cost=steady["run_costs"],
        steady_state_net=steady["net"],
        manual_cost_per_task=uc.manual_cost_per_task,
        agent_cost_per_task=(steady["run_costs"] / uc.tasks_per_month) if uc.tasks_per_month else 0.0,
        breakdown=totals,
    )
    if with_break_even:
        result.break_even_automation_rate = break_even_automation_rate(uc)
    return result


def break_even_automation_rate(uc: UseCase) -> float | None:
    """Smallest automation rate (other inputs fixed) at which NPV >= 0, or None if unreachable."""
    upper = 1.0 - uc.assist_rate

    def npv_at(rate: float) -> float:
        return calculate(replace(uc, automation_rate=rate), with_break_even=False).npv

    if npv_at(0.0) >= 0:
        return 0.0
    if npv_at(upper) < 0:
        return None
    lo, hi = 0.0, upper
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if npv_at(mid) >= 0:
            hi = mid
        else:
            lo = mid
    return hi


# ------------------------------------------------------------------ sensitivity

SENSITIVITY_PARAMS = (
    "tasks_per_month",
    "automation_rate",
    "minutes_per_task_manual",
    "loaded_hourly_cost",
    "llm_cost_per_task",
    "infra_cost_per_month",
    "maintenance_fte",
    "build_cost",
    "ramp_months",
    "error_rate_agent",
)


def _scaled(uc: UseCase, param: str, factor: float) -> UseCase:
    value = getattr(uc, param) * factor
    if param == "automation_rate":
        value = min(value, 1.0 - uc.assist_rate)
    elif param == "error_rate_agent":
        value = min(value, 1.0)
    elif param == "ramp_months":
        value = int(round(value))
    return replace(uc, **{param: value})


def sensitivity(uc: UseCase, delta: float = 0.2, params: tuple[str, ...] = SENSITIVITY_PARAMS) -> list[dict[str, Any]]:
    """One-at-a-time sensitivity: NPV when each input is lowered / raised by ``delta``.

    Returns rows sorted by NPV swing, largest first (a tornado chart as a table).
    """
    rows = []
    for param in params:
        base = getattr(uc, param)
        if not base:
            continue
        low = calculate(_scaled(uc, param, 1.0 - delta), with_break_even=False).npv
        high = calculate(_scaled(uc, param, 1.0 + delta), with_break_even=False).npv
        rows.append(
            {
                "param": param,
                "base": base,
                "npv_at_minus": low,
                "npv_at_plus": high,
                "swing": abs(high - low),
            }
        )
    return sorted(rows, key=lambda r: r["swing"], reverse=True)


# --------------------------------------------------------------------- scenarios

SCENARIOS: dict[str, dict[str, float]] = {
    "pessimistic": {
        "automation_rate": 0.70,
        "tasks_per_month": 0.80,
        "llm_cost_per_task": 1.50,
        "build_cost": 1.30,
        "maintenance_fte": 1.30,
        "ramp_months": 1.5,
    },
    "base": {},
    "optimistic": {
        "automation_rate": 1.15,
        "tasks_per_month": 1.10,
        "llm_cost_per_task": 0.80,
        "build_cost": 0.90,
        "maintenance_fte": 0.90,
        "ramp_months": 0.75,
    },
}


def scenarios(uc: UseCase) -> dict[str, ROIResult]:
    out = {}
    for name, factors in SCENARIOS.items():
        scenario = uc
        for param, factor in factors.items():
            scenario = _scaled(scenario, param, factor)
        out[name] = calculate(scenario)
    return out


# ------------------------------------------------------------ use-case prioritization

DEFAULT_WEIGHTS = {
    "business_value": 0.30,
    "feasibility": 0.25,
    "data_readiness": 0.20,
    "risk": 0.15,  # score 5 = low risk
    "strategic_fit": 0.10,
}


def priority_score(scores: dict[str, float], weights: dict[str, float] | None = None) -> float:
    """Weighted score from 0 to 100. Each criterion is scored 1 (worst) to 5 (best)."""
    weights = weights or DEFAULT_WEIGHTS
    missing = set(weights) - set(scores)
    if missing:
        raise ValueError(f"Missing scores for: {sorted(missing)}")
    for key in weights:
        if not 1 <= scores[key] <= 5:
            raise ValueError(f"{key} must be scored 1 to 5, got {scores[key]}")
    total_weight = sum(weights.values())
    weighted = sum(weights[k] * scores[k] for k in weights) / total_weight
    return round(weighted / 5.0 * 100.0, 1)


# ---------------------------------------------------------------------- reporting


def _money(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def format_report(uc: UseCase, r: ROIResult) -> str:
    be = "n/a (not reachable)" if r.break_even_automation_rate is None else f"{r.break_even_automation_rate:.0%}"
    payback = "not within horizon" if r.payback_month is None else f"month {r.payback_month}"
    roi = "n/a" if r.roi_pct is None else f"{r.roi_pct:,.0f}%"
    b = r.breakdown
    lines = [
        f"Use case: {uc.name}",
        f"Horizon: {r.horizon_months} months, discount rate {uc.discount_rate_annual:.0%}",
        "",
        f"Net value (undiscounted): {_money(r.net_value)}",
        f"NPV:                      {_money(r.npv)}",
        f"ROI:                      {roi}",
        f"Payback:                  {payback}",
        f"Break-even automation:    {be} (modeled: {uc.automation_rate:.0%})",
        "",
        "Steady state (full adoption), per month",
        f"  Benefits:   {_money(r.steady_state_benefit)}",
        f"  Run costs:  {_money(r.steady_state_run_cost)}",
        f"  Net:        {_money(r.steady_state_net)}",
        f"  Manual cost per task: ${r.manual_cost_per_task:,.2f}   Agent run cost per task: ${r.agent_cost_per_task:,.2f}",
        "",
        "Horizon totals",
        f"  Labor saved (automated): {_money(b.get('labor_automated', 0))}",
        f"  Labor saved (assisted):  {_money(b.get('labor_assisted', 0))}",
        f"  Quality value:           {_money(b.get('quality', 0))}",
        f"  Other benefits:          {_money(b.get('other', 0))}",
        f"  Build:                   {_money(-r.build_cost)}",
        f"  LLM:                     {_money(-b.get('llm', 0))}",
        f"  Rework:                  {_money(-b.get('rework', 0))}",
        f"  Infrastructure:          {_money(-b.get('infra', 0))}",
        f"  Maintenance:             {_money(-b.get('maintenance', 0))}",
    ]
    return "\n".join(lines)
