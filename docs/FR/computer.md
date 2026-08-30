# Utiliser votre écran

Comodor peut piloter la machine comme le fait une personne — regarder l'écran,
déplacer la souris, cliquer et taper — dans n'importe quelle application, pas
seulement un navigateur.

C'est la chose la plus puissante qu'il sache faire et la plus dangereuse. Lisez
le [modèle d'autorisations](#permission) avant de l'activer.

> **Windows uniquement, pour l'instant.** Les backends macOS et Linux ne sont
> pas écrits. Sur ces plateformes, l'outil n'est pas proposé du tout, plutôt que
> proposé et en échec — voir [Pourquoi il n'y est pas](#why-it-is-not-there).

---

## À quoi cela ressemble

Vous regardez cela se produire. Avant que le pointeur ne bouge, une auréole
apparaît là où il va cliquer :

```
   ┌─────────────────────────────────────────┐
   │   Comodor · 14m 32s left, anywhere      │   ← the panel, top centre
   │   move the mouse to a corner to stop    │
   └─────────────────────────────────────────┘


              ╭──────────╮
              │   Save   │      ◎  ← the halo, drawn before it moves
              ╰──────────╯
                              clicking (842, 517)
```

Le pointeur y voyage ensuite pendant environ un tiers de seconde au lieu de se
téléporter, et une onde marque l'endroit où le clic s'est posé.

**La pause n'est pas de la décoration.** C'est le moment où vous pouvez encore
l'arrêter. Un curseur qui saute et clique dans le même instant ne vous laisse
rien.

Si l'agent tourne ailleurs — un serveur, un conteneur — la même chose apparaît
à la place dans l'[interface web](web.md) : l'image qu'il a regardée, avec un
marqueur là où il a agi.

---

## L'activer

Deux étapes, volontairement. Aucune ne survient d'elle-même.

**1. Permettre à l'outil d'exister**, dans `~/.comodor/config.json` :

```json
{
  "computer": {
    "enabled": true
  }
}
```

Tant que ce n'est pas défini, l'outil n'est pas proposé du tout au modèle. Il
n'est pas dans la liste des outils, donc il ne peut pas le demander ni être
convaincu de l'utiliser.

**2. Lui permettre d'agir**, au moment où cela compte :

```
/computer 15m              fifteen minutes, anywhere on screen
/computer 1h this app      one hour, only while the current window is in front
/computer                  how things stand
/computer stop             end it now
```

Ou laissez le modèle demander. La première fois qu'il a besoin de l'écran, vous
obtenez ceci :

```
  Let Comodor use your screen, mouse and keyboard?

  It will be able to see everything on your screen and to click and type
  anywhere, in any application.

  Screenshots go to the model. Whatever is on screen goes with them - open
  messages, tokens, anything visible. Redaction works on text and cannot
  read pixels.

  It will never touch a password manager, a window asking for a password,
  a locked screen, or Comodor's own window.

  To stop it at any moment: move your mouse into a corner of the screen.

  [15 minutes]  [15 minutes, this app only]  [1 hour]  [no]
```

---

## L'arrêter

**Déplacez la souris dans un coin de l'écran.** C'est tout.

Cela fonctionne même quand l'agent tient le pointeur, ce qu'aucun raccourci
clavier ne peut garantir — l'agent peut être en train de taper dans une fenêtre
à cet instant. C'est aussi ce que les gens font réellement quand leur écran se
met à bouger tout seul.

Effleurer un coin met fin à l'exécution et retire l'autorisation. Demander de
nouveau vaut nouvelle autorisation.

L'agent peut toujours cliquer lui-même dans un coin — le bouton Démarrer, une
boîte de fermeture. Il se souvient où il a laissé le pointeur ; seul un pointeur
déplacé vers un endroit où personne ne l'avait mis compte comme vous.

Autres façons de l'arrêter, quand vos mains sont sur le clavier :

```
/computer stop       ends the permission
Esc                  stops the current task
```

---

## Autorisations

Une autorisation réunit trois choses à la fois, et aucune d'elles n'est une case
à cocher.

| | |
|---|---|
| **Un périmètre** | partout, ou une application via le titre de sa fenêtre |
| **Un compte à rebours** | elle expire, et le temps restant est affiché à l'écran en permanence |
| **Une issue** | le coin, qui fonctionne même pendant que le pointeur est piloté |

Elle est vérifiée **avant chaque action**, pas une seule fois au départ. Une
fenêtre qui apparaît au milieu d'une session autorisée est repérée.

### Refusé quoi que vous ayez autorisé

- Un gestionnaire de mots de passe — 1Password, Bitwarden, KeePass, LastPass,
  Dashlane, NordPass, et les magasins d'identifiants du système.
- Toute fenêtre dont le titre mentionne un mot de passe, une phrase secrète, la
  2FA ou un code à usage unique.
- Une application de portefeuille ou de portefeuille matériel — MetaMask,
  Ledger Live, Trezor.
- Tout ce qui ressemble à des opérations bancaires en ligne.
- Un écran verrouillé.
- **La fenêtre de Comodor elle-même.** Un agent qui clique dans le terminal qui
  le pilote tape dans son propre invite.

Ajoutez les vôtres :

```json
{
  "computer": {
    "never": ["Internal HR", "Payroll"]
  }
}
```

Correspondance recherchée n'importe où dans le titre de la fenêtre, sans
distinction de casse.

### Ce qu'une autorisation n'est pas

Elle n'est **jamais écrite dans votre fichier de configuration**. Fermer Comodor
y met fin. Il n'existe pas de « toujours autoriser » pour l'écran, et cette
absence est délibérée.

Un dépôt ne peut pas activer cela. `computer` ne figure pas dans la liste de ce
que le `.comodor/config.json` d'un projet peut définir, et un dépôt qui tente
est refusé à voix haute. Voir [Sécurité](safety.md#what-a-repository-may-set).

---

## Ce qui est envoyé au modèle

**Des captures d'écran, et tout ce qui y est visible.** Cela mérite qu'on s'y
arrête.

Si un gestionnaire de mots de passe est ouvert derrière votre éditeur, si une
fenêtre de discussion contient un message, si une clé d'API s'affiche dans un
terminal — tout cela est dans l'image, et l'image part vers le fournisseur que
vous avez configuré.

La rédaction de Comodor agit sur le texte et ne peut pas lire les pixels. Il
n'y a pas de contour : la fonctionnalité est « laisser le modèle voir votre
écran ».

Conseils pratiques :

- Fermez ce que vous ne colleriez pas dans une fenêtre de discussion.
- Utilisez `/computer 1h this app` pour qu'il n'agisse que lorsqu'une fenêtre
  est au premier plan — même s'il *voit* toujours tout ce qui figure dans la
  capture.
- Préférez l'[outil navigateur](browser.md) quand le travail est une page web.
  Il renvoie du texte, pas des pixels, et coûte une fraction du prix.

---

## Ce qu'il peut faire

Dix-sept actions, derrière un seul outil. Les noms sont ceux d'Anthropic, car
les modèles sont entraînés sur ce vocabulaire.

### Regarder

| Action | Ce qu'il fait |
|---|---|
| `screenshot` | L'écran actif. `whole_desktop: true` pour tous les écrans. |
| `zoom` | Une région, en pleine résolution — sa façon de lire les petits textes |
| `cursor_position` | Où se trouve le pointeur |

### Pointer

| Action | |
|---|---|
| `mouse_move` | Se déplacer quelque part sans cliquer |
| `left_click` `right_click` `middle_click` | Avec des touches modificatrices facultatives |
| `double_click` `triple_click` | Le triple clic sélectionne une ligne dans la plupart des éditeurs |
| `left_click_drag` | D'un point à un autre |
| `left_mouse_down` `left_mouse_up` | Pour tout ce qu'un glisser ne peut pas exprimer |
| `scroll` | Haut, bas, gauche, droite, par crans de molette |

### Taper

| Action | |
|---|---|
| `type` | Du texte, caractère par caractère — correct sur chaque disposition de clavier |
| `key` | `Return`, `ctrl+s`, `alt+Tab`, `F5`, `Page_Down`, … |
| `hold_key` | Maintenir une touche ou une combinaison pendant une durée |
| `wait` | Laisser quelque chose à l'écran se terminer |

Le texte est saisi **caractère par caractère, pas par position de touche**.
Enfoncer la touche où `@` se trouve sur un clavier américain produit autre chose
sur un clavier français ; nommer le caractère produit `@` partout, y compris sur
les dispositions dépourvues de touche pour lui.

---

## Tapé n'est pas arrivé

Les applications réécrivent ce qu'on y tape.

Le Notepad de Windows 11 a la correction automatique activée par défaut. Y taper
`ümlaut` produit `umlaut`. Rien ne s'est perdu en route — chacun des trente
caractères accentués et non latins arrive intact quand il est envoyé seul, et
`üxqzv` à la même position reste intact. C'est l'application qui l'a modifié.

Comodor le dit à chaque `type` :

```
Typed 29 characters. Applications can autocorrect or reformat what is
typed into them - take a screenshot if what arrived matters.
```

Si le texte exact compte — un champ de mot de passe, une valeur de
configuration, un message de commit — faites-le regarder de nouveau.

---

## Les captures d'écran et ce qu'elles coûtent

Une capture d'écran est ce que cet outil envoie de plus cher.

La taille est ajustée à ce que le modèle accepte : un bord long de 2 576 pixels
et un budget de jetons. Le budget par défaut est de 1 600 jetons visuels, ce qui
donne une image lisible sur chacun des écrans essayés.

| Votre écran | Au budget par défaut | Coût |
|---|---|---|
| 1920 × 1080 | 1480 × 833 | ~1 590 jetons |
| 3840 × 1080 | 2068 × 582 | ~1 554 jetons |
| 3840 × 2160 | 1064 × 599 | ~836 jetons |

**Ne le réglez pas trop bas.** Le conseil habituel de « capturer à 1280 de
large » suppose un écran 16:9. Sur un écran 3840 × 1080, cela signifie une
réduction d'un facteur trois, et à cette taille le modèle reçoit un texte qu'il
ne peut pas lire — alors il devine au lieu de demander. Mesuré sur cet écran :
des libellés de menu illisibles à 1280 de large, parfaitement nets à 2068.

```json
{
  "computer": {
    "screenshot_tokens": 1600
  }
}
```

700 est économique et reste lisible sur un ordinateur portable. 4784 est le
maximum que le modèle accepte.

**Les anciennes captures d'écran sont supprimées automatiquement.** Seules les
deux dernières restent dans la conversation ; les autres deviennent une ligne
indiquant qu'il y en avait une. Sans cela, une tâche en trente étapes
transporterait près de cinquante mille jetons de pixels, presque tous consacrés
à décrire un écran qui a depuis été cliqué. Changez cela avec
`agent.keep_screenshots` si vous en avez une raison.

---

## Tous les paramètres

```json
{
  "computer": {
    "enabled": false,
    "screenshot_tokens": 1600,
    "grant_seconds": 900,
    "travel_seconds": 0.32,
    "overlay": true,
    "never": []
  }
}
```

| Paramètre | Défaut | |
|---|---|---|
| `enabled` | `false` | Si l'outil est proposé au modèle ou non |
| `screenshot_tokens` | `1600` | Lisibilité face au prix. Maximum 4784 |
| `grant_seconds` | `900` | Durée d'une autorisation simple |
| `travel_seconds` | `0.32` | Temps de trajet du pointeur. `0` fonctionnerait et serait insupportable à regarder |
| `overlay` | `true` | Dessiner l'auréole et le panneau. Désactivé pour une machine sans personne devant |
| `never` | `[]` | Titres de fenêtres supplémentaires à ne jamais toucher |

---

## Pourquoi il n'y est pas

Si `computer` ne figure pas parmi les outils, l'une de ces affirmations est
vraie :

**La plateforme n'a pas de backend.** Windows uniquement, pour l'instant.
L'outil n'est pas proposé plutôt que proposé et en échec à chaque fois — un
outil que le modèle voit sans jamais pouvoir l'utiliser invite à un appel
gaspillé à chaque tour.

**Il est désactivé.** `computer.enabled` vaut `false` par défaut.

Demandez-lui directement :

```
/computer
```

```
no screen control: it is switched off. Set computer.enabled in your config.
```

---

## Sous le capot

Pour les curieux, et pour quiconque le porte vers une autre plateforme.

**Aucune dépendance.** La capture d'écran passe par GDI via `ctypes` ; la
réduction d'échelle est un `StretchBlt` en mode `HALFTONE`, qui moyenne au lieu
d'abandonner des pixels — la différence entre un petit texte lisible et du
moucheté. L'encodage PNG tient en `zlib` et `struct`, une quarantaine de lignes.
La saisie passe par `SendInput`.

**La prise en compte des DPI est déclarée avant toute lecture d'une métrique
d'écran.** Sur un écran à l'échelle 125 % — le défaut sur la plupart des
ordinateurs portables Windows — un processus qui ne s'est pas déclaré compatible
DPI se fait dire que l'écran est plus petit qu'il ne l'est, et chaque clic
retombe à court d'exactement le facteur d'échelle. La cause est invisible ; on
dirait que le modèle ne sait pas viser.

**Les coordonnées sont converties en un seul endroit.** Le modèle répond dans
les pixels de l'image qu'on lui a montrée, qui est un recadrage réduit d'un
écran dont l'origine ne lui a jamais été indiquée. `Shot.to_screen` est le seul
code qui le sait, car une deuxième copie est une deuxième occasion de se
tromper.

**La superposition est une fenêtre traversable par les clics, jamais
focalisée.** `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE`, pour que le
pointeur atteigne ce qui est dessous et que le clavier reste où il était. Elle
tourne dans son propre fil avec sa propre boucle d'événements, et un échec de
dessin est une image manquante, pas une fonctionnalité manquante — l'agent
fonctionne sans aucun affichage.

Porter vers macOS ou Linux signifie écrire un fichier à côté de `win32.py` avec
la même douzaine de fonctions. Rien au-dessus de cette couche n'importe
`ctypes`.

---

## Voir aussi

- [Sécurité et autorisations](safety.md) — le reste du modèle d'autorisations
- [Le vrai navigateur](browser.md) — moins cher, quand le travail est une page web
- [Depuis un navigateur](web.md) — le voir travailler depuis ailleurs
- [Coût](cost.md) — ce que coûte réellement une longue session de bureau
