# Questions

L'ambiguïté a deux mauvaises fins. L'agent choisit une lecture, construit la
mauvaise chose, et vous coûte un cycle de relecture. Ou il demande en prose,
une question à la fois, et vous passez quatre tours à régler ce qui aurait pu
être réglé en un seul écran.

Comodor prend une troisième voie. Quand une demande peut se lire de plus d'une
façon, l'agent détermine *tout* ce dont il n'est pas sûr d'abord, puis vous le
soumet sous forme d'un court formulaire à choix multiples — trois ou quatre
questions, répondues en une quinzaine de secondes, avant qu'une ligne ne soit
écrite.

Sollicité pour « add rate limiting to the web server », il a lu dix fichiers
puis posé ceci :

```
┏━  3 questions  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                          ┃
┃    ☐  Client identity   ☐  Over-limit   ☐  Scope                         ┃
┃                                                                          ┃
┃  How should clients be identified for rate limiting?                     ┃
┃                                                                          ┃
┃   › ☐ By IP address (recommended)                                        ┃
┃        The server already reads client_address for the loopback check.   ┃
┃     ☐ By token                                                           ┃
┃     ☐ Something else                                                     ┃
┃                                                                          ┃
┃    0 of 3 answered                                                       ┃
┃                                                                          ┃
┗━━━━━━━━━━━━━━  ↑↓ move · ←→ question · space pick · enter next · esc  ━━┛
```

Notez la deuxième ligne de la première option. Il avait lu `web/server.py`
avant de demander, et la question porte sur la décision que cette lecture ne
pouvait pas trancher.

## Dans le terminal

```
left / right      previous and next question
up / down         move within the options
space             pick — and toggle, when several answers may apply
enter             pick, then jump to the next unanswered question;
                  on the last one, send
ctrl+s            send from anywhere
escape            close without answering
```

La bande d'onglets porte une marque par question, pour que vous voyiez d'un
coup d'œil lesquelles sont encore en attente sans les visiter chacune.

## Dans le navigateur

Le même formulaire en boîte de dialogue. Cliquez sur les onglets ou utilisez
les touches fléchées, cliquez sur une option, et pressez **Send**. `Escape` la
ferme.

## La dernière ligne

Chaque question se termine par **Something else** et une zone de saisie. Elle
est ajoutée par Comodor, pas par le modèle, et le modèle ne peut pas la
retirer — tout l'intérêt de la ligne est de couvrir ce à quoi le modèle n'a
pas pensé. Taper dedans remplace l'option sélectionnée, et choisir une option
efface ce qui a été tapé, pour qu'une question ne revienne jamais avec deux
réponses contradictoires.

## Passer outre

Envoyer un formulaire avec des questions sans réponse est acceptable, et ce
n'est pas la même chose que de le fermer. On dit exactement à l'agent
lesquelles vous avez laissées de côté, et que vous ne les avez donc pas
contraintes — ainsi il les tranche lui-même et dit dans quel sens il est allé.

Fermer entièrement le formulaire (**Not now**, ou `escape`) dit à l'agent de
continuer avec des valeurs par défaut raisonnables et de **ne plus jamais
demander**. Un second formulaire soumis à quelqu'un qui vient de fermer le
premier est le comportement qui rend une fonctionnalité pareille détestée.

## Quand il ne demande pas

Par conception, pas par accident :

- Tout ce qu'il peut découvrir en lisant le projet. Il lit d'abord.
- La permission de continuer. C'est le rôle de la demande d'approbation.
- Vous confirmer son plan.
- Une décision avec une valeur par défaut évidente. Il la prend et vous dit
  qu'il l'a fait.

## Limites

Quatre questions au plus, et quatre options chacune au plus — plus la ligne
écrivez-la-vous-même, qui ne consomme pas l'une des quatre. Au-delà, ce n'est
plus un formulaire rapide mais un interrogatoire, et un agent qui a besoin de
six réponses devrait demander les quatre qui comptent et déduire le reste.

Le formulaire attend trente minutes. Passé ce délai il revient sans réponse et
l'agent continue, pour qu'un formulaire laissé ouvert sur une machine où
personne n'est ne puisse retenir une exécution indéfiniment.

## Pour d'autres modèles

L'outil s'appelle `ask` et il est `SAFE`, ce qui signifie qu'il est disponible
aussi en mode plan — la planification est le moment où l'ambiguïté mord le
plus fort.

La facilité avec laquelle un modèle y recourt varie. Chaque modèle testé
demande quand la demande le réclame manifestement et se tait quand elle ne le
fait pas, mais si le vôtre construit sur une supposition, dire *« ask me about
anything you need to decide first »* dans votre propre message le règle
immédiatement.
