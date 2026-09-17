"""Pose l'amorce agentique et la vérification d'identité sur les runtimes Hermes (root, serveur des agents).

Usage (depuis le poste) :
  ssh … 'cat > /tmp/agents.tar' < agents.tar ; ssh … 'sudo python3 /tmp/agents/installer.py'

Pour chaque runtime (almalinux = historique, vigil = AZZCOM, coord = AZZCO, azzadmin = AZZMIN) :
  * SOUL.md : bloc « amorce » inséré sous le premier titre (idempotent, remplacé s'il existe) ;
    AZZCOM reçoit en plus le bloc « style » (réponses courtes) ;
  * vtlvs.py : commande `contexte` (pour qui j'agis) et prise en charge d'une délégation signée
    (`--delegation` ou VTLVS_DELEGATION) ;
  * SKILL.md : la vérification du contexte en première ligne de l'outil.
Sauvegarde *.avant-amorce à la première pose. Aucun redémarrage : SOUL.md et les compétences
sont relus à chaque session.
"""
import pathlib
import re
import shutil

ICI = pathlib.Path(__file__).parent
AMORCE = (ICI / "amorce.md").read_text(encoding="utf-8").strip()
STYLE = (ICI / "style-azzcom.md").read_text(encoding="utf-8").strip()
RUNTIMES = {"almalinux": [], "vigil": [STYLE], "coord": [], "azzadmin": []}


def sauvegarder(p: pathlib.Path) -> None:
    s = p.with_name(p.name + ".avant-amorce")
    if not s.exists():
        shutil.copy2(p, s)


def poser_bloc(texte: str, bloc: str, nom: str) -> str:
    motif = re.compile(rf"<!-- vtlvs:{nom}:debut.*?<!-- vtlvs:{nom}:fin -->", re.S)
    if motif.search(texte):
        return motif.sub(lambda _m: bloc, texte)
    # sous l'amorce si elle est déjà là ; sinon après le premier titre de niveau 1
    fin = texte.find("<!-- vtlvs:amorce:fin -->")
    if nom != "amorce" and fin != -1:
        pos = fin + len("<!-- vtlvs:amorce:fin -->")
        return texte[:pos] + "\n\n" + bloc + "\n" + texte[pos:]
    m = re.search(r"^# .*$", texte, flags=re.M)
    pos = m.end() + 1 if m else 0
    return texte[:pos] + "\n" + bloc + "\n\n" + texte[pos:]


CONTEXTE_PARSER = '    sub.add_parser("contexte")\n'
CONTEXTE_CMD = '''    if a.cmd == "contexte":
        _print(_call("GET", "/agent/contexte", pour))
        return
'''

for user, extras in RUNTIMES.items():
    home = pathlib.Path(f"/home/{user}/.hermes")
    soul = home / "SOUL.md"
    if soul.exists():
        sauvegarder(soul)
        t = poser_bloc(soul.read_text(encoding="utf-8"), AMORCE, "amorce")
        t = re.sub(r"\n?<!-- vtlvs:style:debut.*?<!-- vtlvs:style:fin -->\n?", "\n", t, flags=re.S)
        for bloc in extras:
            t = poser_bloc(t, bloc, "style")
        soul.write_text(t, encoding="utf-8")
        shutil.chown(soul, user, user)
        print(f"{user}: SOUL.md — amorce{' + style' if extras else ''}")

    script = home / "skills/business/vtlvs-coordinateur/scripts/vtlvs.py"
    if script.exists():
        code = script.read_text(encoding="utf-8")
        if 'add_parser("contexte")' not in code:
            sauvegarder(script)
            code = code.replace('    sub.add_parser("sessions")\n', CONTEXTE_PARSER + '    sub.add_parser("sessions")\n', 1)
            code = code.replace('    a = ap.parse_args()\n    pour = a.pour\n',
                                '    a = ap.parse_args()\n    pour = a.pour\n\n' + CONTEXTE_CMD, 1)
            # délégation signée : permet d'agir pour une autre personne qui l'a confiée
            code = code.replace('        "X-Learn-Principal": "agent",\n',
                                '        "X-Learn-Principal": "agent",\n'
                                '        **({"X-Vtlvs-Delegation": os.environ["VTLVS_DELEGATION"]} if os.environ.get("VTLVS_DELEGATION") else {}),\n', 1)
            script.write_text(code, encoding="utf-8")
            shutil.chown(script, user, user)
            print(f"{user}: vtlvs.py — commande contexte + délégation signée")

    skill = home / "skills/business/vtlvs-coordinateur/SKILL.md"
    if skill.exists():
        s = skill.read_text(encoding="utf-8")
        ligne = "| **Toujours en premier** : pour qui j'agis, mon rôle, mes droits | `contexte` |\n"
        if ligne not in s and "| Besoin | Commande |\n|---|---|\n" in s:
            sauvegarder(skill)
            s = s.replace("| Besoin | Commande |\n|---|---|\n", "| Besoin | Commande |\n|---|---|\n" + ligne, 1)
            skill.write_text(s, encoding="utf-8")
            shutil.chown(skill, user, user)
            print(f"{user}: SKILL.md — contexte en premier")
