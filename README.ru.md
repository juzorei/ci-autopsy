# ci-autopsy

[English](README.md) | [Русский](README.ru.md)

Скилл и CLI, которые ставят диагноз упавшей сборке GitHub Actions до того, как все начнут гадать.

У красного CI есть три честных исхода: инфраструктурный шум, сломанный workflow или реальная ошибка в коде. Основные потери времени — из-за их смешения: перезапуск сломанного workflow пять раз или отладка таймаута registry как будто это твой код. `autopsy` сначала заставляет классифицировать.

```text
$ autopsy run https://github.com/owner/repo/actions/runs/123456789
== Test (ubuntu-latest, 3.13) (failure)
   pytest    2 failed, 431 passed, 1 skipped
   failed    tests/test_pricing.py::test_discount_applied
   first     AssertionError: assert 90.0 == 85.0
   verdict   test-failure
   evidence  L3: FAILED tests/test_pricing.py::test_discount_applied - AssertionError: ...
   action    Deterministic-looking test failures. This is the code; reproduce locally, not more triage.
```

## Как устроено

- `autopsy run <url-или-id>` — забирает логи упавших джоб через авторизованный `gh` (без токенов и ключей), классифицирует каждую, печатает вердикт + улики + извлечённую сводку pytest + нужное действие.
- `autopsy classify <логи...>` — та же классификация на сохранённых логах офлайн; `--json` для скриптов.
- `autopsy rules` — печатает встроенный реестр сигнатур (чистый TOML). Расширяй через `--rules your.toml` или заменяй целиком через `--replace`: у каждого проекта свой повторяющийся шум, а правила — это данные, не код: коммить их, ревьюй в PR.
- `autopsy demo` — десять реалистичных синтетических логов (диск у бегунка, 429 от registry, отмена из-за concurrency, флак на занятом порту), чтобы попробовать всё без репозитория.

Восемь вердиктов приоритизированы, а не взаимоисключающи: job, упавший по таймауту, завершается строкой «cancelled», поэтому `timeout` главнее `cancel` — но обычная отмена из-за concurrency всё равно главнее тестов, видимых в её логе. Список приоритетов кодирует уроки реальных прогонов.

Python 3.11+, кроме установленного `gh` для `run` зависимостей нет.

## Скилл

[skills/ci-triage](skills/ci-triage) превращает CLI в процесс, который агент проходит сам: забрать только упавшие джобы, классифицировать до каких-либо действий, выбрать действие под вердикт (перезапуск / чинить YAML / чинить код), подтвердить флак перед исправлением циклами сидов и повторными прогонами, обучить autopsy шуму проекта файлом правил в репозитории и закончить трёхстрочным отчётом, на который человек может опереться.

## Установка

```bash
pip install ci-autopsy             # CLI
npx skills add juzorei/ci-autopsy  # скилл, для любого поддерживаемого агента
```

Как плагин Claude Code: `/plugin marketplace add juzorei/ci-autopsy`.

## Ещё из портфеля

Один из серии прицельных наборов «скилл + CLI» одного автора:

- [loglens](https://github.com/juzorei/loglens) — триаж больших логов — как autopsy триажит упавший CI
- [flakehunt](https://github.com/juzorei/flakehunt) — докажи, что тест флакает, до перезапуска
- [bumpmap](https://github.com/juzorei/bumpmap) — вторая половина сломанного PR: обновления зависимостей

Остальные — в [профиле juzorei](https://github.com/juzorei?tab=repositories).

## Рамки

Для триажа сбоев в собственных репозиториях и CI. Честный карантин флаков (linked issue + срок годности) вместо тихого скипывания — часть контракта скилла.

Лицензия MIT.
