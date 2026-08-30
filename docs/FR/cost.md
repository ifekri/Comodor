# Coût

Ce que coûte une session, et comment la faire coûter moins sans la dégrader.

```
/cost
```

```
This session

- prompt tokens: 84,210
- output tokens: 3,180
- served from cache: 72,418 (86% of the prompt)
- cost: $0.1904
- saved by caching: $0.4126 (68%)
- context used: 87,390 / 1,000,000
- compactions: 0

Brain

- lessons: 812
- skills: 4
- episodes: 137 (83% succeeded)
```

---

## Le cache d'invite, qui est l'essentiel

Chaque requête renvoie les parties qui ne changent pas — l'invite système, les
schémas d'outils, la conversation jusqu'ici. Les fournisseurs re-servent un
préfixe identique à l'octet près à environ un dixième du prix.

Comodor est construit autour de cela, et c'est activé par défaut :

```json
{ "agent": { "prompt_cache": true, "prompt_cache_ttl": "5m" } }
```

Mesuré sur des sessions réelles : **86 % des tokens d'entrée servis depuis le
cache**.

### Pourquoi rien de dynamique ne va dans l'invite système

Le cache ne fonctionne que sur un préfixe identique à l'octet près à celui de
la fois précédente. L'invite système *est* ce préfixe. Tout ce qui change par
tour — les leçons rappelées, la compétence correspondante, l'heure du jour —
l'invalide, et vous payez le prix fort pour tout, à chaque tour.

Ainsi les leçons rappelées circulent sur le *tour*, comme partie du message
utilisateur. Ce seul changement a fait passer le taux de succès mesuré du cache
de 72 % à 87 %.

Si vous ajoutez des instructions permanentes de votre cru, mettez-les dans
`agent.system_prompt_extra`, qui est stable, plutôt que de les faire varier.

### Le cache d'une heure

```json
{ "agent": { "prompt_cache_ttl": "1h" } }
```

Coûte environ 25 % de plus pour *écrire* une entrée et la garde une heure au
lieu de cinq minutes. Cela vaut la peine si vous revenez plusieurs fois à une
session ; c'est du gaspillage pour une seule salve de travail.

---

## Plafonds

```json
{
  "agent": {
    "max_steps": 0,
    "max_seconds": 3600,
    "max_cost_usd": 2.0
  }
}
```

Le premier atteint arrête la tâche, et `0` signifie aucune limite. `stopped`
dans `--json` dit lequel c'était.

**Il n'y a pas de limite de pas par défaut.** Vingt-quatre pas, ce n'est rien
sur un vrai code source — un refactor traversant une douzaine de fichiers en
est arrivé à bout en pleine réflexion — et un nombre de pas n'a aucun rapport
avec le danger : dix pas à lire des fichiers ne coûtent presque rien. Les
plafonds qui correspondent au danger sont le temps et l'argent, et ceux-là
restent actifs. Fixez `max_steps` à un nombre si vous voulez un arrêt dur en
retour.

Quand l'un d'eux arrête une tâche, le message dit comment passer outre, et
dire « continue » reprend là où c'en était.

### Quand la limite ne peut pas se déclencher

**Une limite de dépense ne fonctionne que pour un modèle avec un tarif
publié.**

Le tableau des tarifs laisse délibérément les prix vides pour les modèles dont
il n'est pas sûr — inventer un prix produit des nombres faux, ce qui est pire
que rien. Pour un modèle sans prix, le compteur de coût affiche zéro, donc
`spent >= max_cost_usd` n'est jamais vrai et la limite ne se déclenche jamais.

Comodor le dit plutôt que de vous laisser croire que vous êtes protégé :

```
the $2.00 spend limit cannot be enforced for gpt-4o — no published rate is
known, so the cost meter reads zero. The step and time limits still apply.
```

Dit au début d'une session, et dans `comodor doctor` :

```
  warn  spend limit    $2.00 per task cannot be enforced for gpt-4o
                       → No published rate is known for this model, so the
                         cost meter reads zero and the limit never fires.
                         The step and time limits still apply.
```

Pour un modèle qui tourne sur votre propre machine, il dit autre chose, car là
cela ne coûte rien pour commencer.

---

## Ce qui coûte réellement de l'argent

**Les captures d'écran.** Environ 1 600 tokens visuels chacune au budget par
défaut — et encore autant à chaque tour où elles restent dans la conversation.
Comodor garde les deux dernières et remplace les autres par une ligne disant
qu'il y en avait une. Sans cela, une tâche de bureau de trente pas emporte près
de cinquante mille tokens de pixels décrivant des écrans qui ont depuis été
cliqués.

```json
{ "agent":    { "keep_screenshots": 2 } }
{ "computer": { "screenshot_tokens": 1600 } }
```

Ne fixez pas `screenshot_tokens` trop bas. Une image que le modèle ne peut pas
lire est pire que pas d'image : il devine au lieu de demander. Voir
[Utiliser votre écran](computer.md#screenshots-and-what-they-cost).

**Les grosses sorties d'outils.** Bornées par `agent.max_tool_chars`. Ce qui ne
tient pas est écrit dans un fichier auquel on dit au modèle comment lire, ainsi
il ne paie que s'il regarde.

**La réflexion.** Un appel au modèle à la fin d'une tâche. Orientez-le vers un
modèle moins cher :

```json
{ "learning": { "reflect_model": "claude-haiku-4-5" } }
```

Ou désactivez-le. La voie gratuite — corrections, règles, annonces — continue
de fonctionner dans tous les cas. [Comment il apprend](learning.md#the-two-lanes).

**Le navigateur, quand il regarde.** `browse` renvoie du texte par défaut et
une capture d'écran seulement sur demande, car l'image d'une page coûte la
même chose à chaque fois et ne peut pas être rognée.

---

## Ne rien dépenser

```bash
ollama pull qwen2.5-coder:14b
comodor setup       # choose Ollama
```

Tout ce que dit cette documentation fonctionne, sans coût, sauf là où il est
dit autrement. [Choisir un modèle](models.md#running-it-locally-for-nothing).

---

## Voir aussi

- [Choisir un modèle](models.md) — ce que chaque fournisseur facture
- [Configuration](configuration.md#agent--how-it-works) — chaque bouton
