# Comment il apprend

La plupart des agents oublient dès que la session se termine. Celui-ci observe
ce que vous changez dans sa sortie et le garde.

---

## L'idée

Les éloges sont bon marché et les corrections coûtent cher, donc les corrections
sont ce dont il apprend.

Quand vous modifiez un fichier qu'il a écrit, ou quand vous lui dites
franchement qu'il se trompait, cela devient une **leçon** : une règle courte
avec une confiance qui monte à chaque fois qu'elle se vérifie et décroît quand
elle reste inutilisée. Les leçons sont rappelées quand la situation ressemble à
celle qu'elles décrivent, et injectées dans ce tour — jamais dans l'invite
système, ce qui coûterait le cache d'invite.

Rien ne quitte votre machine. Le cerveau est un fichier SQLite sous votre
répertoire de configuration.

---

## Les deux voies

### Réflexe — gratuit, immédiat, toujours actif

Aucun appel au modèle, aucun jeton, aucun délai.

- **Corrections.** Vous changez `"` en `'` dans un fichier qu'il a écrit. C'est
  une différence, et une différence est un fait.
- **Règles.** Il lit votre code existant une fois, au début, et en tire les
  conventions — l'indentation, le style de guillemets, la façon dont les tests
  sont nommés.
- **Annonces.** Quand une règle est appliquée, il le dit, en une ligne. Une
  règle que vous ne pouvez pas voir est une règle que vous ne pouvez pas
  corriger.
- **Prérécupération.** Le rappel démarre pendant que vous tapez encore.

Cette voie reste active même quand la réflexion est désactivée, parce qu'elle ne
coûte rien.

### Réflexion — un appel au modèle, après une tâche

À la fin d'une tâche, il regarde ce qui s'est passé et note ce qu'il devrait
retenir. Celle-ci coûte un appel. Utilisez un modèle moins cher si vous voulez :

```json
{ "learning": { "reflect_model": "claude-haiku-4-5" } }
```

Ou désactivez-la, en gardant le Réflexe :

```json
{ "learning": { "reflect": false } }
```

---

## Lui enseigner, délibérément

Dites-le dans la conversation. Une correction — « non, pas comme ça », ou
modifier ce qu'il a écrit — devient une leçon dont la confiance monte quand
elle se vérifie. Quelque chose de durable dit en mots simples — « nous
utilisons pytest, jamais unittest », « cette base de données est Postgres » —
l'agent le note sur son étagère de mémoire avec l'outil `memory`, où cela se
trouve en tête de chaque tour ; `comodor journey show` liste ce qui s'y trouve.

Refuser une demande d'autorisation lui enseigne aussi. Un refus est le signal
de préférence le plus net que l'interface recueille, et il est traité comme tel.

---

## Voir ce qu'il sait

```bash
comodor journey show
```

Tout ce qu'il a appris, du plus ancien au plus récent — chaque leçon avec ce
qui la déclenche, ce qu'elle dit, son genre et sa confiance actuelle, et les
règles de la maison qu'il a tirées de votre code plutôt que de ce que vous lui
auriez dit. `comodor journey remove ID` en retire une qui était fausse.

---

## Voir si cela fonctionne

```bash
comodor insights
```

```
◈ Corrections per task down 100% since the first tasks in this project.

metric                trend                       now  vs first
Steps per task        ▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇    6.1      ↑10%
Corrections per task  ████████▅▅▅▅▅▅▅▅▁▁▁▁▁▁▁▁    0.0     ↓100%
Approvals asked       ▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅    2.0         —
Tokens per task       ▁▁▁▂▂▂▃▃▃▄▄▄▅▅▅▆▆▆▇▇▇███  12.0K      ↑40%
First-try success     ▁██████▁██████▁██████▁██    86%         —

brain    7 rules · 812 lessons · 24 corrections learned from
history  24 tasks over 8 days
success  83% overall
```

**La ligne du haut est celle qui compte.** Si les corrections par tâche ne
baissent pas, l'apprentissage ne fonctionne pas — et le panneau met cela en
tête dans les deux cas, au lieu de l'enterrer sous l'activité. Tout le reste du
tableau est de l'effort ; celle-là est le résultat.

---

## Le rappel, et pourquoi il n'est pas dans l'invite système

Les leçons rappelées voyagent sur le tour, dans le message utilisateur, et non
dans l'invite système.

C'est une décision de coût. La mise en cache d'invite ne fonctionne que sur un
préfixe identique à l'octet près, et l'invite système est ce préfixe. Y mettre
quoi que ce soit de dépendant de la requête invalide le cache à chaque tour.
Déplacer le rappel sur le tour a fait passer le taux d'atteinte du cache mesuré
de 72 % à 87 %. Voir [Coût](cost.md).

---

## Les mots qu'il apprend de vous

Il apprend aussi lesquels de *vos* mots vont ensemble, à partir de vos propres
tâches achevées — que « the parser » et « tokenise » appartiennent au même
coin de votre base de code. Cela ne coûte ni jetons ni appel au modèle ; c'est
du comptage.

C'est ce qui permet à une leçon enregistrée à propos de « the tokeniser » de
remonter quand vous demandez « the lexer ».

```json
{ "learning": { "associative": true } }
```

---

## Portée

```json
{ "learning": { "share_scope": "project" } }
```

`project` garde les leçons dans le dépôt où elles ont été apprises — le défaut
qui s'impose, car une convention juste dans une base de code est fausse dans une
autre. `global` les partage partout.

---

## L'oubli

Une leçon inutilisée décroît. `half_life_days` (45 par défaut) règle la vitesse,
et `min_confidence` (0.15) est le plancher en dessous duquel elle cesse d'être
rappelée.

Cela compte : une base de code change d'avis, et un agent qui porte une
convention vieille de deux ans avec une confiance totale est pire qu'un qui a
oublié.

---

## Le désactiver

```json
{ "learning": { "enabled": false } }
```

Tout fonctionne toujours. Il commence simplement chaque session comme un
inconnu.

---

## Où il vit

```
~/.comodor/brain.db
```

SQLite. Le vôtre. `comodor uninstall` le retire et dit combien il pesait.

---

## Voir aussi

- [Compétences](skills.md) — les procédures que vous écrivez, plutôt que les leçons qu'il déduit
- [Coût](cost.md) — pourquoi le rappel est sur le tour et non dans le préfixe
