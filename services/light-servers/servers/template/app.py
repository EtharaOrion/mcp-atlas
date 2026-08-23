from fastmcp import FastMCP
from typing import Any, Dict, List
from string import Template
import re
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, meta

mcp = FastMCP("TemplateServer")


_jinja_env = Environment(autoescape=False)


@mcp.tool
async def render_jinja(template: str, context: Dict[str, Any]) -> str:
    """Render a Jinja2 `template` string using the given `context` variables."""
    return _jinja_env.from_string(template).render(**context)


@mcp.tool
async def render_jinja_strict(template: str, context: Dict[str, Any]) -> str:
    """Render Jinja2 with StrictUndefined: raises on undefined variables."""
    env = Environment(autoescape=False, undefined=StrictUndefined)
    return env.from_string(template).render(**context)


@mcp.tool
async def render_mustache(template: str, context: Dict[str, Any]) -> str:
    """Naively render a mustache-style `{{ name }}` template with `context`. No sections/partials."""
    def repl(m: re.Match) -> str:
        key = m.group(1).strip()
        return str(context.get(key, ""))
    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", repl, template)


@mcp.tool
async def interpolate(template: str, context: Dict[str, Any]) -> str:
    """Render a Python `str.format`-style template like 'Hello {name}' using `context`."""
    return template.format(**context)


@mcp.tool
async def render_percent(template: str, context: Dict[str, Any]) -> str:
    """Render a Python %-style template like 'Hello %(name)s' using `context`."""
    return template % context


@mcp.tool
async def render_dollar(template: str, context: Dict[str, Any]) -> str:
    """Render a string.Template `$var` template using `context`."""
    return Template(template).substitute(context)


@mcp.tool
async def render_dollar_safe(template: str, context: Dict[str, Any]) -> str:
    """Like `render_dollar` but leaves missing placeholders in place instead of raising."""
    return Template(template).safe_substitute(context)


@mcp.tool
async def render_env_style(template: str, env: Dict[str, str]) -> str:
    """Render an env-style `$VAR` or `${VAR}` template using the given `env` dict."""
    def repl(m: re.Match) -> str:
        key = m.group(1) or m.group(2)
        return env.get(key, m.group(0))
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", repl, template)


@mcp.tool
async def render_curly(template: str, context: Dict[str, Any]) -> str:
    """Render a single-curly `{var}` template. Escapes `{{` and `}}` as literal braces."""
    return template.format(**context)


@mcp.tool
async def extract_variables(template: str, syntax: str = "jinja") -> List[str]:
    """Return a sorted list of variable names referenced by `template` in the given `syntax`.

    Supported syntaxes: jinja, mustache, dollar, percent, format.
    """
    s = syntax.lower()
    if s == "jinja":
        try:
            ast = _jinja_env.parse(template)
            return sorted(meta.find_undeclared_variables(ast))
        except TemplateSyntaxError:
            return []
    if s == "mustache":
        return sorted(set(re.findall(r"\{\{\s*([\w.]+)\s*\}\}", template)))
    if s == "dollar":
        return sorted(set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", template)))
    if s == "percent":
        return sorted(set(re.findall(r"%\(([\w.]+)\)[sdifr]", template)))
    if s == "format":
        return sorted({m.group(1) for m in re.finditer(r"\{(\w+)[^}]*\}", template)})
    raise ValueError(f"unknown syntax: {syntax}")


@mcp.tool
async def validate_template(template: str, syntax: str = "jinja") -> Dict:
    """Return {valid: bool, error?: str} for the template under the given `syntax`."""
    s = syntax.lower()
    try:
        if s == "jinja":
            _jinja_env.parse(template)
        elif s == "dollar":
            Template(template).template
        elif s == "format":
            template.format_map({})
        return {"valid": True}
    except TemplateSyntaxError as e:
        return {"valid": False, "error": f"jinja: {e.message}"}
    except (KeyError, ValueError, IndexError) as e:
        return {"valid": False, "error": str(e)}


@mcp.tool
async def render_batch(template: str, contexts: List[Dict[str, Any]], syntax: str = "jinja") -> List[str]:
    """Render the same `template` against each context in `contexts` using the chosen `syntax`."""
    s = syntax.lower()
    if s == "jinja":
        compiled = _jinja_env.from_string(template)
        return [compiled.render(**c) for c in contexts]
    if s == "mustache":
        return [await render_mustache.__wrapped__(template, c) for c in contexts]
    if s == "format":
        return [template.format(**c) for c in contexts]
    if s == "dollar":
        return [Template(template).substitute(c) for c in contexts]
    raise ValueError(f"unknown syntax: {syntax}")


@mcp.tool
async def escape_jinja(text: str) -> str:
    """Escape Jinja2 special characters in `text` so it renders as literal output."""
    return text.replace("{", "{{ '{' }}").replace("}", "{{ '}' }}")


@mcp.tool
async def count_placeholders(template: str, syntax: str = "jinja") -> int:
    """Return the count of distinct placeholder occurrences in `template`."""
    variables = await extract_variables.__wrapped__(template, syntax)
    return len(variables)


@mcp.tool
async def render_with_defaults(template: str, context: Dict[str, Any], defaults: Dict[str, Any], syntax: str = "jinja") -> str:
    """Render `template` filling any missing keys from `defaults`."""
    merged = {**defaults, **context}
    if syntax.lower() == "jinja":
        return _jinja_env.from_string(template).render(**merged)
    return template.format(**merged)


@mcp.tool
async def preview(template: str, syntax: str = "jinja") -> Dict:
    """Return summary metadata about `template`: syntax, variable list, length, line count."""
    return {
        "syntax": syntax,
        "length": len(template),
        "lines": template.count("\n") + 1,
        "variables": await extract_variables.__wrapped__(template, syntax),
    }


@mcp.tool
async def strip_comments_jinja(template: str) -> str:
    """Remove Jinja2 comment blocks `{# ... #}` from `template`."""
    return re.sub(r"\{#.*?#\}", "", template, flags=re.DOTALL)
