# Compétences

Une compétence est une procédure écrite que l'agent suit quand le travail la
réclame.

Pas une invite que vous collez à chaque fois — un fichier qu'il charge tout
seul quand la situation correspond.

---

## En obtenir

`comodor setup` propose la bibliothèque une fois, à la fin. Déplacez-vous avec
les touches fléchées, pressez **espace** pour cocher autant que vous voulez, et
**entrée** installe tout. Rien n'est coché au départ, et entrée sans rien de
coché n'en prend aucune — on ne vous donne jamais quelque chose que vous
n'avez pas demandé.

```
┌─ Skills ──────────────────────────────────────────────────┐
│    ☑ review        Review a change before it is committed │
│ ›  ☐ commit-style  Match the commit messages already here │
│    ☑ python-tests  Write tests the way this project does  │
└───────────────────────────────────── 2 selected ──────────┘
  ↑↓ move   space select   enter install 2   tab more   esc cancel
```

**Une ligne par compétence**, pour que la liste entière tienne sur un écran
quelle que soit la longueur de la bibliothèque, et la fenêtre suit la flèche
au lieu de traîner derrière. Certaines de ces descriptions vont jusqu'à un
paragraphe — **tab** ouvre la version complète pour l'élément pointé par la
flèche, dans le même cadre, et tab une nouvelle fois le referme.

Taper filtre la liste, ce qui est plus rapide que faire défiler dès qu'il y en
a plus d'une poignée. Les coches sont conservées pendant que vous filtrez, si
bien que vous pouvez restreindre la liste, cocher quelque chose, effacer le
filtre et cocher autre chose.

Sans terminal, il peut prendre la main — un tube, un script, `curl | sh` — la
même question est posée sous forme de liste numérotée, une page à la fois :

| | |
|---|---|
| `1,3` ou `1 3` | prendre ceux-là |
| `m` / `b` | page suivante, page précédente |
| `/word` | ne montrer que ce qui correspond |
| `?7` | lire la description entière du numéro 7 |
| entrée | terminé |

Les numéros sont absolus : le numéro 92 est la quatre-vingt-douzième
compétence, quelle que soit la page ou la recherche que vous regardez, si bien
qu'un numéro noté reste le numéro que vous tapez.

---

## En utiliser une

```bash
comodor skills browse            # what is available
comodor skills add review        # install it
comodor skills list              # what you have
```

```
/skills                          # the same, in the interface
```

Dès lors, quand vous demandez quelque chose que couvre une compétence, elle
est chargée et l'agent la suit. On vous le dit quand cela arrive :

```
  ▸ skill: review — Review a change for correctness before it is committed
```

Une compétence dont vous ne voyez pas l'application est une compétence que
vous ne pouvez pas corriger.

---

## En écrire une

Un dossier avec un `SKILL.md` dedans :

```
~/.comodor/skills/our-tests/SKILL.md
```

```markdown
---
name: our-tests
description: How tests are written and run in this project.
---

# Tests in this project

- pytest, never unittest.
- One file per module, mirroring `src/`.
- Name the test after the behaviour, not the function:
  `test_an_empty_input_raises`, not `test_parse_2`.
- Never mock what you can construct.

## Running them

    uv run pytest -x -q

Not `python -m pytest` — the project needs the venv's own interpreter.
```

La **description** est ce qui compte le plus. C'est ce que Comodor confronte à
votre demande pour décider s'il charge la compétence du tout, alors écrivez-la
comme la situation, pas comme un titre.

Redémarrez, ou `/skills`, et elle est là.

### Embarquer des fichiers

Une compétence peut porter des fichiers à côté de `SKILL.md` :

```
~/.comodor/skills/our-tests/
  SKILL.md
  references/
    fixtures.md
    conventions.md
```

`SKILL.md` pointe vers eux ; l'agent n'en lit un que lorsqu'il en a besoin.
Cela garde la compétence elle-même courte — ce qui compte, car la compétence
est chargée dans le tour et une longue coûte des tokens que le détail ait été
nécessaire ou non.

---

## Par projet

```
./.comodor/skills/<name>/SKILL.md
```

Commité avec le dépôt, pour que toute personne qui y travaille ait les mêmes
procédures. Les compétences d'un projet sont chargées à côté des vôtres.

---

## Le budget

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000
  }
}
```

`top_k` est combien peuvent être chargées pour un tour ; `max_tokens` est le
plafond de ce qu'elles peuvent coûter ensemble. Une compétence trop grande
pour tenir est ignorée, et on vous dit laquelle — le silence ici a été un vrai
bogue un jour, où une compétence surdimensionnée déplaçait discrètement des
plus petites.

---

## Les gérer

```bash
comodor skills add review taste output    # several at once
comodor skills update                     # refresh installed ones
comodor skills remove review
comodor skills list                       # with versions
```

---

## Voir aussi

- [Comment il apprend](learning.md) — des leçons qu'il déduit, plutôt que des procédures que vous écrivez
- [Ce que l'agent peut faire](tools.md) — les outils qu'une compétence lui apprend à utiliser
