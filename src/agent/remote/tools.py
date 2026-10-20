"""
Arquivo: src/agent/remote/tools.py
Nome: tools.py
Propósito: expor as ferramentas do agente que operam no computador remoto do projeto.
Responsabilidade: camada de apresentação — ferramentas que traduzem chamadas do modelo em ações via SSH.
Componentes: read_file, write_file, list_dir, edit_file, delete_file, make_dir, move_file, glob_files, search_grep.
Dependências: agent.remote.ssh, agent.tools.diffing.
Observações: todo caminho passa pela trava de segurança e precisa ficar dentro do projeto remoto.
"""
from __future__ import annotations

from typing import Any

from agent.remote.ssh import RemoteConfig, RemoteError, SshTransport
from agent.tools.diffing import unified_diff_text


def transport(ctx: Any) -> SshTransport:
    """Transporte SSH do contexto (o projeto tem computador remoto configurado)."""
    config: RemoteConfig = ctx.remote
    return SshTransport(config)


def _guard(ctx: Any, path: str) -> dict | None:
    """Mantém a trava de segurança: o caminho tem de ficar dentro do projeto."""
    raw = str(path or "")
    if raw.startswith("/") or ".." in raw.replace("\\", "/").split("/"):
        return {"success": False, "error": "path fora do projeto"}
    return None


async def read_file(ctx: Any, args: dict) -> dict:
    """Lê uma janela de linhas de um arquivo remoto.

    Args:
        ctx: contexto da ferramenta, com a configuração remota do projeto.
        args: argumentos da chamada (`path`, `offset`, `limit`).

    Returns:
        O conteúdo lido, o offset, o total de linhas e a marca de truncamento.
    """
    path = str(args.get("path") or "")
    bad = _guard(ctx, path)
    if bad:
        return bad
    ssh = transport(ctx)
    try:
        content = await ssh.read_text(path)
    except RemoteError as exc:
        return {"success": False, "error": str(exc), "path": path}
    lines = content.splitlines()
    total = len(lines)
    try:
        offset = max(1, int(args.get("offset") or args.get("start_line") or 1))
    except (TypeError, ValueError):
        offset = 1
    raw_limit = args.get("limit", args.get("max_lines"))
    limit: int | None
    try:
        limit = int(raw_limit) if raw_limit not in (None, "") else None
    except (TypeError, ValueError):
        limit = None
    truncated = False
    if limit is None and total > 2000:
        limit = 2000
        truncated = True
    if offset > total and total:
        return {"success": False, "error": "offset além do fim do arquivo", "total_lines": total}
    window = lines[offset - 1 :] if limit is None else lines[offset - 1 : offset - 1 + max(limit, 0)]
    if limit is not None and offset - 1 + limit < total:
        truncated = True
    return {
        "success": True,
        "path": path,
        "content": "\n".join(window),
        "offset": offset,
        "total_lines": total,
        "truncated": truncated,
        "remote": True,
    }


async def write_file(ctx: Any, args: dict) -> dict:
    """Grava um arquivo remoto, criando as pastas intermediárias.

    Args:
        ctx: contexto da ferramenta, com a configuração remota do projeto.
        args: argumentos da chamada (`path`, `content`).

    Returns:
        O caminho gravado e a quantidade de bytes escritos.
    """
    path = str(args.get("path") or "")
    bad = _guard(ctx, path)
    if bad:
        return bad
    content = args.get("content") or ""
    ssh = transport(ctx)
    try:
        parent = str(path).rsplit("/", 1)[0] if "/" in str(path) else ""
        if parent:
            await ssh.make_dir(parent)
        size = await ssh.write_text(path, content)
    except RemoteError as exc:
        return {"success": False, "error": str(exc), "path": path}
    return {"success": True, "path": path, "bytes": size, "remote": True}


async def list_dir(ctx: Any, args: dict) -> dict:
    """Lista o conteúdo de uma pasta remota.

    Args:
        ctx: contexto da ferramenta, com a configuração remota do projeto.
        args: argumentos da chamada (`path`).

    Returns:
        A lista de entradas encontradas na pasta.
    """
    path = str(args.get("path") or ".")
    bad = _guard(ctx, path)
    if bad:
        return bad
    ssh = transport(ctx)
    try:
        entries = await ssh.list_dir(path)
    except RemoteError as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "entries": [{"path": item["path"], "kind": "file"} for item in entries],
        "truncated": False,
        "remote": True,
    }


async def edit_file(ctx: Any, args: dict) -> dict:
    """Substitui um trecho de um arquivo remoto.

    Args:
        ctx: contexto da ferramenta, com a configuração remota do projeto.
        args: argumentos da chamada (`path`, `old_string`, `new_string`, `replace_all`).

    Returns:
        O caminho editado, a quantidade de substituições e o diff unificado.
    """
    path = str(args.get("path") or "")
    old = args.get("old_string", args.get("old", args.get("search")))
    new = args.get("new_string", args.get("new"))
    if not isinstance(old, str) or not isinstance(new, str):
        return {"success": False, "error": "old_string e new_string são obrigatórios"}
    if old == "":
        return {"success": False, "error": "old_string vazio"}
    bad = _guard(ctx, path)
    if bad:
        return bad
    ssh = transport(ctx)
    try:
        content = await ssh.read_text(path)
    except RemoteError as exc:
        return {"success": False, "error": str(exc), "path": path}
    count = content.count(old)
    if count == 0:
        return {"success": False, "error": "trecho não encontrado", "path": path}
    if count > 1 and not args.get("replace_all"):
        return {"success": False, "error": f"trecho ambíguo ({count} vezes); use replace_all ou um trecho único"}
    updated = content.replace(old, new) if args.get("replace_all") else content.replace(old, new, 1)
    try:
        await ssh.write_text(path, updated)
    except RemoteError as exc:
        return {"success": False, "error": str(exc), "path": path}
    diff = unified_diff_text(path, content, updated)
    return {
        "success": True,
        "path": path,
        "replacements": count if args.get("replace_all") else 1,
        "remote": True,
        **diff,
    }


async def delete_file(ctx: Any, args: dict) -> dict:
    """Remove um arquivo ou pasta remoto.

    Args:
        ctx: contexto da ferramenta, com a configuração remota do projeto.
        args: argumentos da chamada (`path`).

    Returns:
        O caminho removido.
    """
    path = str(args.get("path") or "")
    bad = _guard(ctx, path)
    if bad:
        return bad
    ssh = transport(ctx)
    try:
        await ssh.remove(path)
    except RemoteError as exc:
        return {"success": False, "error": str(exc), "path": path}
    return {"success": True, "path": path, "remote": True}


async def make_dir(ctx: Any, args: dict) -> dict:
    """Cria uma pasta remota.

    Args:
        ctx: contexto da ferramenta, com a configuração remota do projeto.
        args: argumentos da chamada (`path`).

    Returns:
        O caminho criado.
    """
    path = str(args.get("path") or "")
    if not path:
        return {"success": False, "error": "path obrigatório"}
    bad = _guard(ctx, path)
    if bad:
        return bad
    ssh = transport(ctx)
    try:
        await ssh.make_dir(path)
    except RemoteError as exc:
        return {"success": False, "error": str(exc), "path": path}
    return {"success": True, "path": path, "remote": True}


async def move_file(ctx: Any, args: dict) -> dict:
    """Move ou renomeia um caminho remoto.

    Args:
        ctx: contexto da ferramenta, com a configuração remota do projeto.
        args: argumentos da chamada (`from`, `to`).

    Returns:
        Os caminhos de origem e destino.
    """
    src = args.get("from") or args.get("source") or args.get("path")
    dst = args.get("to") or args.get("dest") or args.get("destination")
    if not isinstance(src, str) or not isinstance(dst, str):
        return {"success": False, "error": "from e to são obrigatórios"}
    for value in (src, dst):
        bad = _guard(ctx, value)
        if bad:
            return bad
    ssh = transport(ctx)
    try:
        parent = str(dst).rsplit("/", 1)[0] if "/" in str(dst) else ""
        if parent:
            await ssh.make_dir(parent)
        await ssh.move(src, dst)
    except RemoteError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "from": src, "to": dst, "remote": True}


async def glob_files(ctx: Any, args: dict) -> dict:
    """Busca arquivos remotos pelo nome.

    Args:
        ctx: contexto da ferramenta, com a configuração remota do projeto.
        args: argumentos da chamada (`pattern`).

    Returns:
        A lista de caminhos encontrados, limitada a 2000 entradas.
    """
    pattern = args.get("pattern") or args.get("glob") or ""
    if not isinstance(pattern, str) or not pattern:
        return {"success": False, "error": "pattern obrigatório"}
    bad = _guard(ctx, pattern)
    if bad:
        return bad
    ssh = transport(ctx)
    if ssh.config.is_windows:
        cmd = f"Get-ChildItem -Recurse -File -Filter '{pattern}' | ForEach-Object {{ $_.FullName }}"
    else:
        cmd = f"find . -type f -name {pattern!r}"
    try:
        result = await ssh.run(cmd)
    except RemoteError as exc:
        return {"success": False, "error": str(exc)}
    matches = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {"success": True, "matches": matches[:2000], "truncated": len(matches) > 2000, "remote": True}


async def search_grep(ctx: Any, args: dict) -> dict:
    """Busca um padrão no conteúdo dos arquivos remotos.

    Args:
        ctx: contexto da ferramenta, com a configuração remota do projeto.
        args: argumentos da chamada (`pattern`).

    Returns:
        A lista de caminhos que contêm o padrão, limitada a 2000 entradas.
    """
    pattern = str(args.get("pattern") or args.get("query") or "")
    if not pattern:
        return {"success": False, "error": "pattern obrigatório"}
    ssh = transport(ctx)
    if ssh.config.is_windows:
        cmd = f"Get-ChildItem -Recurse -File | Select-String -Pattern '{pattern}' | ForEach-Object {{ \"$($_.Path):$($_.LineNumber)\" }}"
    else:
        cmd = f"grep -rIl --exclude-dir=.git -e {pattern!r} ."
    try:
        result = await ssh.run(cmd)
    except RemoteError as exc:
        return {"success": False, "error": str(exc)}
    matches = [line.strip().lstrip("./") for line in result.stdout.splitlines() if line.strip()]
    return {"success": True, "matches": matches[:2000], "remote": True}
