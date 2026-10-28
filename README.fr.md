[中文](README.zh-CN.md) · [English](README.md) · **Français** · [日本語](README.ja.md) · [Русский](README.ru.md)

# 1846 Self-Play Arena · laboratoire d'auto-jeu 1846

Une plateforme locale d'auto-jeu et d'auto-apprentissage pour **1846: The Race for the Midwest** : le moteur de règles open source de 18xx.games exécute les règles, avec des bots guidés par les règles, une boucle d'entraînement par auto-jeu à réseau de neurones, une interface web d'observation avec rejeu, et une boîte à outils d'audit qui valide les valeurs de règles sur des journaux de parties réelles.

[![verify](https://github.com/Pig9013/1846-selfplay-arena/actions/workflows/verify.yml/badge.svg)](https://github.com/Pig9013/1846-selfplay-arena/actions/workflows/verify.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Version 1.2.0** · Windows · fonctionne hors ligne · sans compte sur le site ni modèle cloud

> **Nouveautés de la version 1.2.0** : auto-jeu continu avec 316 parties utilisables, actions en 48 dimensions et résidu neuronal borné, score de pose tenant compte de la rotation, prior de 665 parties humaines à la place de la règle codée en dur sur Chicago, analyse toutes les 1000 parties. Comparaison complète : [RELEASE_NOTES.en.md](RELEASE_NOTES.en.md).

---

## Le problème que ce projet résout

Les détails des règles 18xx (coûts de terrain, revenus hors carte variant selon la phase, bonus est–ouest, tuiles propres à Z/Chicago, blocage par les gares, inventaire de tuiles) sont très faciles à rater dans une IA maison. Ce projet confie les « règles » à un moteur éprouvé en partie réelle sur le site, garde les « décisions » pour lui, et vérifie l'implémentation des règles à l'aide de **journaux de parties réelles** :

- **Exécution des règles** : `18xx-master` (tobymao/18xx, MIT) est l'unique arbitre ; les bots ne produisent que des candidats, que le moteur valide.
- **Audit de parties réelles** : `audit/` exporte le catalogue de tuiles depuis le moteur, rejoue la pose de voie, les phases et l'attribution des bonus de 95 journaux 18xx.games, et recalcule indépendamment **69 494 revenus de lignes**, avec un taux de concordance de **99,99 %** avec les relevés du site.
- **Boucle d'auto-apprentissage** : une implémentation minimale à la KataGo — échantillonnage d'auto-jeu multiprocessus → entraînement des réseaux politique/valeur → rechargement à chaud du nouveau modèle → évaluation du taux de victoire contre des bases heuristiques.
- **Observable** : la page web affiche en temps réel le plateau, les coûts, les valeurs hors carte, l'attribution des bonus, l'inventaire de tuiles et les emplacements de pose/amélioration par tour.

> 1846 est conçu par Thomas Lehmann et publié par GMT Games. Ce dépôt **ne contient pas** le livret de règles, les éléments graphiques ou un quelconque fichier officiel ; le moteur de règles est un code tiers sous MIT, et les données d'auto-jeu sont produites par les bots de ce projet.

## Fonctionnalités principales

| Module | Description |
| --- | --- |
| Valeurs de règles | Coût de pose = max($20, valeur imprimée) ; les arêtes rivière/montagne/tunnel se paient à la **première connexion** ; tuiles Z / tuiles de Chicago / tuiles ordinaires séparées ; nombre de tuiles limité ; une gare pleine bloque le passage |
| Hors carte et est–ouest | Le revenu hors carte dépend de la phase (jaune/brun) ; E→E interdit, W→W autorisé, Holland et Louisville neutres ; le bonus E/W est la somme des valeurs d'icônes hors carte aux deux extrémités |
| Compagnies privées | Boomtown / Meat Packing / Steamboat agissent par **hex** et par **propriétaire** (ports de Wheeling/Holland +$40, les autres +$20) ; répartition et attribution visibles |
| Bots | Génération de candidats guidée par les règles (vérification des connexions, inventaire de tuiles, couleurs/voie réservée, limites d'actions et de trains), score heuristique, surcouche optionnelle de politique par réseau de neurones |
| Auto-apprentissage | `p1846/selfplay.rb` échantillonne → `train/nnserver.py` infère → `train/trainer.py` entraîne → `train/orchestrate.py` orchestre en continu → `train/analyze.py` analyse toutes les 1000 parties |
| Prior humain | `train/human_playbook.py` produit `human_playbook.md` et `human_prior.json` à partir de 665 parties humaines ; `p1846/human_prior.rb` les traite comme un prior souple, pas comme une règle |
| Analyse | `train/analyze.py` écrit `train/reports/logic-N.md` : structure des actions, taux d'acceptation du 1er candidat, Chicago/C5/Z, corrélations de victoire, comparaison IA vs 665 humains, liste des corrections |
| Observation | Page web locale : plateau, rejeu, actifs des joueurs, tableau des compagnies, raisons des décisions, panneau d'entraînement |
| Audit | `audit/log_audit.py` recalcule les revenus de lignes depuis les journaux réels ; `verify_game.rb` rejoue action par action et vérifie la conservation de la trésorerie |
| Ressources | Processus fils en priorité inférieure à la normale ; concurrence par défaut « cœurs − 2 » ; l'entraînement n'utilise que 2 threads torch |

## Démarrage rapide

### Prérequis

- Windows 10/11, Python 3.12 (la bibliothèque standard suffit à faire tourner la plateforme ; l'entraînement demande PyTorch)
- Le projet fournit un runtime Ruby 3.4.9 portable dans `runtime/` (le Ruby du système n'est pas modifié)
- Le **moteur de règles 18xx** se place **à côté** de ce répertoire : `../18xx-master` (cloner `https://github.com/tobymao/18xx`, ou utiliser un instantané que vous avez déjà)

```
父目录/
├── 1846自战平台/      ← 本仓库
│   ├── server.py
│   ├── arena.rb
│   ├── p1846/
│   ├── train/
│   ├── audit/
│   ├── web/
│   └── runtime/        ← Ruby 运行时（发布包自带，仓库中忽略）
└── 18xx-master/        ← 规则引擎（MIT）
```

### Lancer la plateforme

```bat
启动平台.cmd
```

Ouvrir `http://127.0.0.1:1846` dans un navigateur, choisir le nombre de joueurs et les stratégies de siège, puis lancer une partie en auto-jeu. Sinon :

```bat
python server.py --no-browser --port 1846
```

### Lancer l'auto-apprentissage

```bat
python train\orchestrate.py --workers 6 --minutes 0 --train-every 4 --steps 200 --eval-every 300 --report-every 1000
```

Ou double-cliquer sur `启动训练.cmd`. Les modèles vont dans `train/checkpoints/latest.pt`, les échantillons dans `train/data/`, et le panneau « Entraînement auto-apprentissage » de la page web permet de démarrer et d'arrêter.

### Vérifier les règles

```bat
ruby audit\export_catalog.rb     :: 从引擎导出瓦片目录
python audit\log_audit.py        :: 重算真实日志的线路收入并比对
python verify_all.py runs        :: 逐局重放并核对收入与现金守恒
python tests\\test_audit.py       :: 审计器单元测试（CI 也跑这个）
```

## Structure du dépôt

```
server.py              本机 HTTP 服务、对局/训练管理、静态页面
arena.rb               单局自战循环：候选生成 → 打分/网络 → 引擎执行
engine_boot.rb         原生 Ruby 加载适配（跳过仅供浏览器的 JS 段）
verify_game.rb         独立复核一局（逐行动重放、收入重算、现金守恒）
verify_all.py          批量复核
p1846/board.rb         版图与规则数值导出（成本、边费、外域、标签、库存、奖励归属）
p1846/actions.rb       合法候选生成 + 线路组合搜索（上游 AutoRouter）
p1846/policy.rb        启发式打分
p1846/model.rb         神经网络特征编码（128 维状态 / 40 维动作）
p1846/selfplay.rb      自战采样进程（写出训练样本）
train/net.py           策略/价值网络
train/nnserver.py      本机推理服务（热加载检查点）
train/trainer.py       训练循环（优势加权模仿 + 价值回归）
train/orchestrate.py   多进程自战 + 训练 + 评估编排
audit/                 真实对局日志审计工具与瓦片目录
web/                   中文观战与训练面板
examples/              自战样例（对局 JSON、引擎日志、训练样本）
```

## Formats de données

### Parties (`examples/selfplay/*/game.json`)

Format du moteur 18xx : joueurs, graine, `raw_actions` complet. Rejouable directement avec `verify_game.rb` :

```bat
ruby verify_game.rb "examples\selfplay\4p-seed606\game.json"
```

### Échantillons d'entraînement (`examples/training/*.jsonl.gz`)

Un JSONL par partie, ligne par ligne :

```json
{"type":"decision","actor":"1","state":[128 个浮点],"actions":[[40 个浮点],...],"chosen":0,"prior":[...]}
{"type":"result","scores":{"1":5506,"2":0,...},"z":{"1":0.98,...}}
```

- `state` : caractéristiques de la position (phase, banque, trésorerie/trains/cours des compagnies, actifs des joueurs, statistiques du plateau)
- `actions` : caractéristiques d'action d'au plus 12 candidats légaux à ce point de décision
- `chosen` : indice du candidat réellement exécuté
- `prior` : score heuristique (utilisé pour la distillation)
- `z` : gain de classement normalisé par les actifs finaux (moyenne 0, écart type 1)

## Résultats de la vérification des règles

95 journaux et 69 494 revenus de lignes recalculés, **99,99 %** de concordance avec le site (les 5 écarts viennent de lacunes dans le suivi du plateau propre à l'auditeur). L'audit a confirmé et corrigé deux implémentations faciles à rater :

- **Mail Contract** facture selon les stations **traversées** (y compris les stations sautées par les trains N/M et celles qui ne rapportent aucun revenu) ;
- **Les icônes de port sont collantes** : après l'amélioration d'une ville, l'icône de port reste jusqu'à l'événement de phase IV qui retire le bonus.

La distribution réelle des coûts de pose concorde aussi avec la règle 6.48 : H16 à $40 à la première pose / $20 en amélioration ; B16 à $20 sans franchir une arête de montagne, $60 en la franchissant ; I11 à $60 pour traverser la rivière ; F18 présente les combinaisons 20/40/60/80.

## État de l'auto-apprentissage (1.2)

Dernier instantané (2026-10-28 14:58, `train/reports/logic-0318.md`) : **316 parties utilisables, 182 549 décisions, 0 partie dégénérée** ; 96,8 % de Chicago vert, 93,7 % des trois villes Z, 89,9 % au moins un C5, 35,8 % E/W, 8,9 % de faillites.

- **Auto-jeu continu** : 6 processus jusqu'à l'arrêt ; chaque partie écrit `train/games.jsonl` et `train/data/` ; un rapport `train/reports/logic-N.md` toutes les 1000 parties.
- **Prior humain (1.2)** : les fréquences de 665 parties humaines produisent `human_playbook.md` et `human_prior.json` ; la politique les traite comme un prior souple (10 par défaut, 0 le désactive).
- **Chicago (1.2)** : le codage en dur de la v1.1 (D6 +30/+55/+90/+125, C5 +40, gare de Chicago +58, distance au domicile) a été supprimé. Chicago n'apparaît plus que par les revenus génériques, la connectivité et le prior humain ; les 96,8 % de Chicago vert sont appris, pas écrits dans le score.
- **E/W (1.2)** : rejoindre l'autre côté donne +55, le premier côté +14, s'approcher du côté manquant +2 par hex ; plus de couplage avec Chicago.
- **Plus grand écart** : E/W à 35,8 %, contre 98,8 % dans les 665 parties humaines. La cause est la planification au niveau de la compagnie : IC ne court que vers W, GT/ERIE/NYC/PRR/B&O que vers E, aucune compagnie ne relie les deux.
- **Pas de MCTS** : les positions du moteur ne peuvent pas être clonées à faible coût ; le classement de candidats, la distillation des priors et la pondération par avantage remplacent la recherche arborescente.
- **Taux de victoire** : seulement 2 parties d'évaluation, 0 victoire. L'échantillon est trop petit pour juger le réseau, encore moins pour affirmer qu'il dépasse les humains.

## Limites connues

- Uniquement 1846 standard, 3–5 joueurs, sans règles optionnelles.
- Les candidats des bots ne couvrent pas toutes les capacités spéciales (pose de voie par certaines compagnies privées, échange de trains).
- Le plateau web est un dessin simplifié piloté par les données : valeurs, orientation et adjacences conformes aux règles, mais ce n'est pas l'illustration officielle.
- La séquence d'actions complète des parties réelles n'est pas récupérable via l'API du site (les parties archivées renvoient des actions vides), et les journaux locaux masquent l'étape d'attribution des compagnies privées ; l'audit procède donc par « plateau + recalcul des revenus », et non par rejeu complet.

## Version

Actuellement **1.2.0**. Comparaison complète avec 1.0.0 : [RELEASE_NOTES.en.md](RELEASE_NOTES.en.md) ; changements par version : [CHANGELOG.md](CHANGELOG.md). Feuille de route : compléter les candidats de capacités spéciales, intégrer les emplacements de pose, l'inventaire et l'attribution des bonus aux caractéristiques du réseau, ajouter une évaluation plus stricte sur un pool d'adversaires, et traiter d'abord la planification E/W au niveau des compagnies.

## Résumé

Une arène locale et hors ligne pour **1846: The Race for the Midwest**. Un
checkout voisin du moteur [tobymao/18xx](https://github.com/tobymao/18xx), sous
licence MIT, arbitre chaque action ; ce projet ajoute la génération de candidats
consciente des règles, une interface de plateau et de rejeu pilotée par les
données, une boucle d'auto-apprentissage à la KataGo et un auditeur de règles sur
journaux réels (95 journaux, 69 494 revenus de lignes recalculés, 99,99 % de
concordance). Version 1.2.0. Le dernier échantillon de 316 parties compte
0 partie dégénérée et 182 549 décisions ; un corpus de 665 parties humaines
fournit un prior souple. Le principal écart restant est E/W (35,8 % contre
98,8 % chez les humains). Des parties d'exemple et des échantillons
d'entraînement compressés se trouvent sous `examples/` et dans la release 1.2.0.
Le dépôt ne redistribue ni le moteur de règles, ni le runtime Ruby, ni aucun
élément officiel de 1846.

## Licence et mentions

- Code original de ce dépôt : MIT (voir [LICENSE](LICENSE)).
- Moteur de règles : `tobymao/18xx`, MIT.
- **1846: The Race for the Midwest** est conçu par Thomas Lehmann et publié par GMT Games ; ce projet n'a aucun lien avec l'éditeur et ne contient ni livret de règles, ni illustration de carte, ni aucun composant officiel.
- Les données d'auto-jeu sont produites par les bots de ce projet et librement utilisables pour la recherche.
