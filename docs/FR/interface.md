# L'interface

Ce que vous voyez, ce que vous pressez, et d'où vient tout ce qui est à l'écran.

```bash
comodor          # la lancer
comodor --demo   # toute l'interface, hors ligne, sans clé
```

L'interface tourne sur [Bun](https://bun.sh) — `comodor doctor` dit s'il est
là. Sans lui, `comodor run "..."` fait une tâche sans interface et
`comodor web` en sert une dans le navigateur.

Comment elle est construite — le cœur qu'elle pilote, le protocole entre les
deux, et pourquoi chaque fait à l'écran appartient au cœur plutôt qu'à
l'écran — se trouve dans [tui-v2.md](../tui-v2.md). Cette page est la version
courte pour la personne qui l'utilise.

---

## L'écran

```
┌──────────────────────────────────────────┬───────────────────────┐
│ Comodor   ~/work/my-project  fake-1      │ Agents         1 live │
│                                          │  ● d1 running    12.3s│
│  You                                     │    survey the retries │
│  fix the failing parser test             │ Tasks            2/5  │
│                                          │  ◐ write the tests    │
│  Comodor                                 │  ● read the code      │
│  The test expects parse("") to raise, …  │  ○ run the suite      │
│  ✓ read_file  tests/test_parser.py  0.2s │                       │
│  ● run_shell  pytest tests/…     running…│                       │
│      collected 12 items                  │                       │
│                                          │                       │
├──────────────────────────────────────────┴───────────────────────┤
│ ▌ask for anything                                                │
├──────────────────────────────────────────────────────────────────┤
│  [ACT]   PLAN    ASK    Reads, writes and runs commands…         │
│ ● 1 agent  tab Mode  ctrl+b Work  ctrl+k Commands      42% ctx  │
└──────────────────────────────────────────────────────────────────┘
```

**L'en-tête** nomme le projet, ainsi que le fournisseur et le modèle qui
répondent. C'est ce que rapporte le cœur, pas ce que dit un fichier de
configuration : quand le modèle change — d'ici, depuis un autre client, ou par
le cœur lui-même — l'en-tête suit.

**La conversation** porte en elle la chronologie des outils. Chaque appel
d'outil est là où il s'est produit, sur une ligne : une marque (`●` en cours,
`✓` terminé, `×` échoué), le nom, un résumé d'une ligne, et le temps qu'il a
pris. Un outil en cours montre les dernières lignes de sa sortie ; un outil
terminé se replie, et cliquer dessus ouvre ce que le cœur conserve encore.

**L'établi** — `Ctrl+B` — c'est le travail hors de la conversation : la liste
de tâches que l'agent tient pour lui-même, et les agents en arrière-plan qu'il
a lancés, chacun avec son état. Dans un terminal étroit il s'ouvre par-dessus la
conversation plutôt qu'à côté, et la même touche le ferme.

**Le pied de page** affiche ce que vous pouvez presser, depuis la même liste
d'où les touches sont lues, et ce que cette session a coûté là où le
fournisseur le mesure.

---

## Touches

| Touche | Fait |
|---|---|
| `Entrée` | envoie ce que vous avez tapé |
| `Tab` / `Maj+Tab` | mode suivant / précédent |
| `Ctrl+K` | la palette de commandes — chaque action, avec recherche |
| `Ctrl+B` | ouvrir ou fermer l'établi |
| `Fin` | revenir à la sortie la plus récente après avoir remonté |
| `PageUp` / `PageDown` | faire défiler la conversation |
| `Ctrl+R` | renvoyer un message que le cœur a refusé |
| `Ctrl+C` | arrêter ce qu'il fait ; quitter quand il est inactif |
| `Ctrl+D` | quitter |
| `Échap` | fermer la palette, quitter un champ, ou prendre l'option sûre d'une carte |

Chaque raccourci que montre le pied de page existe ; on ne peut pas afficher
d'indication pour une touche qui n'est pas liée.

---

## Modes

```
ACT    lit, écrit et exécute des commandes, en demandant avant de changer les choses
PLAN   lit et planifie ; ne peut rien écrire, exécuter ni changer
ASK    en discute ; aucun outil du tout
```

`Tab` les fait défiler. L'étiquette bouge quand le cœur confirme, pas quand la
touche s'enfonce : les pressions au sein d'un aller-retour s'accumulent — trois
Tab demandent une fois, pour là où le troisième pointait — et un changement
refusé le dit avec des mots plutôt que de déplacer l'étiquette.

---

## Quand elle vous demande quelque chose

Une carte de permission ou un formulaire de questions prend le clavier tant
qu'elle est affichée, pour qu'une touche destinée à une décision ne puisse pas
aussi envoyer un message.

- **Les flèches** passent d'un choix ou d'une question à l'autre ;
  **Entrée** envoie.
- **Échap** prend l'option sûre propre à la demande — pour une permission c'est
  *refuser*, pour un changement de mode proposé c'est *aucun changement* — et la
  carte dit laquelle. Elle n'autorise jamais rien.
- Il n'y a pas de raccourci à une seule touche pour *autoriser*. Autoriser
  coûte un déplacement jusqu'au choix et un autre pour le confirmer, afin
  qu'une touche pressée pour toute autre raison ne puisse pas autoriser une
  commande.
- Une question qui propose une ligne « écrivez la vôtre » ouvre un champ pour
  cela avec `Espace` ; `Échap` quitte le champ avant d'annuler le formulaire.

Deux choses peuvent attendre en même temps — deux outils parallèles peuvent
chacun demander — et elles sont montrées dans l'ordre d'arrivée, aucune n'est
perdue.

Les touches de mode fonctionnent toujours pendant qu'une carte est affichée. La
palette non : un lanceur par-dessus une décision cacherait ce qui doit être
répondu.

---

## Suivre le fil

Une longue réponse garde la ligne la plus récente en vue. Remontez et elle
cesse de suivre ; la nouvelle sortie ne vous ramène pas en bas, et un marqueur
dit qu'il y a plus en dessous. `Fin` revient à la queue en direct, et envoyer un
nouveau message fait de même.

---

## Sessions

`Ctrl+K` → *Ouvrir une conversation antérieure* liste ce que le cœur a gardé,
et en ouvre une sur place. Le même magasin sert le navigateur, donc une
conversation commencée ici peut être rouverte là-bas.

`comodor --resume` rouvre la plus récente au démarrage ; `--resume ID` en
nomme une.

---

## Copier du texte

Sélectionnez à la souris comme votre terminal le permet. Les options `--theme`
et `--ascii` s'appliquent à ce que les commandes affichent — `setup`,
`doctor`, `help` — pas à l'interface, qui dessine à partir de ses propres
jetons de design.

---

## Texte de droite à gauche

Le persan, l'arabe et les lignes mixtes sont passés au terminal tels qu'écrits,
jamais inversés par le programme. La qualité du rendu d'une ligne mixte est
l'affaire du terminal, et ceux qui le font bien le font bien ici.

---

## Voir aussi

- [tui-v2.md](../tui-v2.md) — comment l'interface est construite, et ce
  qu'elle peut et ne peut pas encore faire
- [questions.md](questions.md) — les formulaires que l'agent vous soumet
- [safety.md](safety.md) — ce qui demande, ce qui ne demande pas, et pourquoi
- [computer.md](computer.md) — le laisser utiliser votre écran
