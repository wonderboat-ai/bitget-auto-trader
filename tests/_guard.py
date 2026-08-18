"""Guarda de backup/restauração dos arquivos reais que a suíte escreve.

Motivo (incidente de 18/08/2026 — perda REAL da trilha do PC1):
`test_smoke.py` e `test_ciclo.py` faziam, cada um por conta própria,
`copy2(audit.jsonl, audit.jsonl.bak-teste)` no import e `move(bak, audit)` no
`atexit` — os DOIS usando exatamente o mesmo nome de backup. Rodando os dois em
sequência (o jeito documentado de rodar a suíte), a sequência abaixo destrói o
original sem deixar cópia:

  1. smoke copia a trilha REAL para o .bak-teste;
  2. smoke escreve eventos de teste na trilha;
  3. o `atexit` do smoke tenta restaurar e FALHA — no Windows a pasta sincroniza
     (Dropbox/OneDrive) e `os.replace`/`copy2` sobre um arquivo com seção
     mapeada aberta dá `PermissionError`/`WinError 1224`. Já era uma falha
     conhecida e considerada inofensiva ("é só rodar de novo");
  4. ciclo começa e copia a trilha — agora CONTAMINADA — por cima do .bak-teste,
     apagando a única cópia do original;
  5. o `atexit` do ciclo consegue restaurar e grava a versão contaminada.

Ou seja: a falha do passo 3, sozinha, era recuperável; combinada com o passo 4
ela vira perda definitiva. Duas invariantes resolvem isso e são o que este
módulo garante:

  A. **Nunca sobrescrever um backup que já existe.** Um .bak presente no import
     significa que uma execução anterior não conseguiu restaurar — o conteúdo
     dele é o original e é a coisa mais valiosa no disco. Nesse caso a guarda
     restaura a partir dele antes de começar, em vez de sobrescrevê-lo.
  B. **Restaurar com fallback que funciona em arquivo mapeado.** `move`/`replace`
     trocam o inode e falham com o arquivo aberto pelo sync; escrever os bytes
     DENTRO do arquivo existente (`open(..., "wb")`) normalmente passa. A guarda
     tenta as duas coisas, com algumas tentativas.

Cada arquivo guardado usa um sufixo próprio por suíte, para que duas suítes
nunca compartilhem o mesmo nome de backup nem por acidente.
"""
from __future__ import annotations

import atexit
import shutil
import time
from pathlib import Path


class FileGuard:
    """Guarda um arquivo real: copia no início, devolve no fim (mesmo se falhar)."""

    def __init__(self, path: Path, suite: str) -> None:
        self.path = Path(path)
        self.bak = self.path.with_name(f"{self.path.name}.bak-{suite}")
        self._had_original = False

        # INVARIANTE A: QUALQUER backup pendente deste arquivo (de qualquer
        # suíte, não só desta) significa que uma execução anterior não
        # conseguiu restaurar — o arquivo no disco está contaminado e o backup
        # é o original. Restaura a partir do MAIS ANTIGO (o mais próximo do
        # original) antes de tirar o backup desta suíte.
        #
        # Olhar só o próprio sufixo não basta, e foi exatamente esse o buraco
        # que destruiu a trilha em 18/08: quem contaminou foi a suíte A e quem
        # rodou em seguida foi a B, com nome de backup diferente.
        pendentes = sorted(self.path.parent.glob(f"{self.path.name}.bak-*"),
                           key=lambda p: p.stat().st_mtime)
        if pendentes:
            origem = pendentes[0]
            print(f"[guard] backup pendente de execucao anterior: {origem.name} "
                  f"-> restaurando {self.path.name} antes de comecar")
            dados = origem.read_bytes()
            if self._write_bytes(dados) and self.path.read_bytes() == dados:
                for p in pendentes:      # só remove depois de confirmar a volta
                    p.unlink(missing_ok=True)
            else:
                raise RuntimeError(
                    f"[guard] nao consegui restaurar {self.path} a partir de "
                    f"{origem}. NAO rode a suite: o original esta em {origem} e "
                    f"seria sobrescrito. Restaure a mao primeiro.")

        if self.path.exists():
            shutil.copy2(self.path, self.bak)
            self._had_original = True

        atexit.register(self.restore)

    def _write_bytes(self, data: bytes) -> bool:
        """Escreve DENTRO do arquivo existente (não troca o inode) — é o que
        funciona quando o Dropbox/OneDrive está com o arquivo mapeado."""
        for tentativa in range(4):
            try:
                with open(self.path, "wb") as fh:
                    fh.write(data)
                return True
            except OSError:
                if tentativa == 3:
                    return False
                time.sleep(0.4 * (tentativa + 1))
        return False

    def _write_back(self) -> bool:
        """Devolve o conteúdo do .bak para o arquivo real. Tenta o caminho que
        funciona em arquivo com seção mapeada (escrever DENTRO do arquivo) antes
        de desistir."""
        if not self.bak.exists():
            return True
        data = self.bak.read_bytes()
        if self._write_bytes(data):
            self.bak.unlink(missing_ok=True)
            return True
        print(f"[guard] FALHA ao restaurar {self.path.name}.\n"
              f"[guard] O ORIGINAL ESTA PRESERVADO EM: {self.bak}\n"
              f"[guard] A proxima execucao da suite restaura a partir dele.")
        return False

    def restore(self) -> None:
        if self._had_original:
            self._write_back()
        elif self.path.exists():
            # não existia antes da suíte: some com o que a suíte criou
            try:
                self.path.unlink()
            except OSError:
                pass


class ContentGuard:
    """Guarda o CONTEÚDO em memória (sem arquivo-irmão no disco).

    Usado para arquivos pequenos de estado, onde um segundo arquivo indo e
    voltando em pasta sincronizada corre risco de race com o sync.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.original = self.path.read_bytes() if self.path.exists() else None
        atexit.register(self.restore)

    def restore(self) -> None:
        try:
            if self.original is None:
                if self.path.exists():
                    self.path.unlink()
            else:
                with open(self.path, "wb") as fh:
                    fh.write(self.original)
        except OSError as exc:
            print(f"[guard] FALHA ao restaurar {self.path.name}: {exc}")

    def reset_to(self, content: str) -> None:
        """Baseline limpo antes dos testes (o original volta no atexit)."""
        self.path.write_text(content, encoding="utf-8")
