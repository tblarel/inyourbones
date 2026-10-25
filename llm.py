"""
Shared OpenAI chat helper.

Picks the model at runtime from the models this API key can actually use, so a
deprecation doesn't break the daily run. Set the OPENAI_MODEL env var (e.g. a
GitHub repo variable) to pin a specific model; auto-selection is the fallback.
"""
import os
import re
import datetime
from openai import OpenAI, BadRequestError, NotFoundError, PermissionDeniedError

# --- SETUP OPENAI ---
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=5)  # SDK default is 2; a 500 has failed the run before

PINNED_MODEL = os.getenv("OPENAI_MODEL", "").strip() or None

# Cheapest-capable first. OpenAI renames tiers between generations
# (mini/nano -> sol/terra/luna), so unknown tiers still qualify but rank last.
TIER_PREFERENCE = ["luna", "mini", "terra", "nano", "sol", "", "astra"]

# Single-word suffixes for specialised models that aren't general chat.
EXCLUDED_TIERS = {"audio", "codex", "cyber", "pro", "realtime", "search", "transcribe", "tts"}

# Only used if the key isn't allowed to list models.
FALLBACK_MODELS = ["gpt-6-luna", "gpt-5.6-luna", "gpt-4.1-mini"]

# gpt-6-luna, gpt-6.1-sol, gpt-4o-mini, gpt-5 ... but not dated snapshots or
# multi-part names like gpt-5-chat-latest / gpt-4o-mini-tts.
CHAT_MODEL_RE = re.compile(r"^gpt-(\d+(?:\.\d+)*)o?(?:-([a-z]+))?$")
SNAPSHOT_RE = re.compile(r"^(.+)-\d{4}-\d{2}-\d{2}$")

# Lowest effort first; stepped down per model, dropped for non-reasoning models.
REASONING_EFFORTS = ["none", "minimal", "low"]

_candidates = None      # models still worth trying this run, best first
_shutdown_dates = {}
_learned_params = {}    # (model, requested params) -> params the model accepted
_announced = None


# --- MODEL SELECTION ---
def shutdown_dates(models):
    """Map model id -> announced shutdown date. Aliases (gpt-5-mini) often have none even
    when their dated snapshot (gpt-5-mini-2025-08-07) does, so they inherit the newest one's."""
    dates = {m.id: getattr(m, "shutdown_date", None) for m in models}
    newest_snapshot = {}
    for model_id in sorted(dates):  # date suffixes sort chronologically
        snapshot = SNAPSHOT_RE.match(model_id)
        if snapshot:
            newest_snapshot[snapshot.group(1)] = dates[model_id]
    return {model_id: date or newest_snapshot.get(model_id) for model_id, date in dates.items()}


def rank_models(models, today=None):
    """Return usable chat model ids from a models.list() result, best first."""
    today = today or datetime.date.today().isoformat()
    dates = shutdown_dates(models)
    candidates = []
    for m in models:
        match = CHAT_MODEL_RE.match(m.id)
        if not match:
            continue
        version, tier = match.group(1), match.group(2) or ""
        if tier in EXCLUDED_TIERS:
            continue
        shutdown = dates[m.id]
        if shutdown and str(shutdown)[:10] <= today:
            continue
        candidates.append({
            "id": m.id,
            "version": tuple(int(p) for p in version.split(".")),
            "tier_rank": TIER_PREFERENCE.index(tier) if tier in TIER_PREFERENCE else len(TIER_PREFERENCE),
            "retiring": bool(shutdown),
        })
    # Newest version within each tier, preferred tiers first, retiring models last.
    candidates.sort(key=lambda c: c["version"], reverse=True)
    candidates.sort(key=lambda c: (c["retiring"], c["tier_rank"]))
    return [c["id"] for c in candidates]


def candidate_models():
    try:
        available = list(client.models.list())
    except Exception as e:
        print(f"⚠️ Could not list OpenAI models ({e}); using fallback list.")
        ranked = list(FALLBACK_MODELS)
    else:
        _shutdown_dates.update(shutdown_dates(available))
        ranked = rank_models(available)
        if not ranked and not PINNED_MODEL:
            ids = ", ".join(sorted(m.id for m in available))
            raise RuntimeError(f"No usable chat model found. Set OPENAI_MODEL to one of: {ids}")

    if PINNED_MODEL:
        ranked = [PINNED_MODEL] + [m for m in ranked if m != PINNED_MODEL]
    return ranked


# --- REQUEST ---
def _relax(params, error):
    """Adjust the param a model rejected. Returns False if there's nothing left to adjust."""
    param = getattr(error, "param", None)
    if param not in params:
        param = next((p for p in params if f"'{p}'" in str(error)), None)
    if param is None:
        return False

    if param == "reasoning_effort" and getattr(error, "code", None) != "unsupported_parameter":
        lower = REASONING_EFFORTS[REASONING_EFFORTS.index(params[param]) + 1:]
        if lower:
            params[param] = lower[0]
            return True
    del params[param]
    return True


def _complete(model, messages, params):
    """Call one model, adapting params until it accepts them. Mutates params."""
    while True:
        try:
            response = client.chat.completions.create(model=model, messages=messages, **params)
        except BadRequestError as e:
            if _relax(params, e):
                continue
            raise
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        if not content and choice.finish_reason == "length" and "max_completion_tokens" in params:
            # Reasoning tokens used up the whole budget.
            del params["max_completion_tokens"]
            continue
        return content


def chat(messages, temperature=None, max_tokens=None):
    """Run a chat completion on the best available model and return the reply text."""
    global _candidates, _announced
    if _candidates is None:
        _candidates = candidate_models()

    requested = {"reasoning_effort": REASONING_EFFORTS[0]}
    if temperature is not None:
        requested["temperature"] = temperature
    if max_tokens is not None:
        requested["max_completion_tokens"] = max_tokens

    last_error = None
    for model in list(_candidates):
        key = (model, tuple(sorted(requested.items())))
        params = dict(_learned_params.get(key, requested))
        try:
            content = _complete(model, messages, params)
        except (NotFoundError, PermissionDeniedError, BadRequestError) as e:
            print(f"⚠️ Model {model} failed ({e.__class__.__name__}: {e}); trying next.")
            _candidates.remove(model)
            last_error = e
            continue

        _learned_params[key] = params
        if model != _announced:
            print(f"🤖 Using OpenAI model: {model}")
            if _shutdown_dates.get(model):
                fix = ("Update or remove the OPENAI_MODEL repo variable." if model == PINNED_MODEL else
                       "No replacement matched auto-selection; set the OPENAI_MODEL repo variable.")
                print(f"::warning::OpenAI model {model} shuts down on {_shutdown_dates[model]}. {fix}")
            _announced = model
        return content

    raise RuntimeError("All candidate OpenAI models failed.") from last_error
