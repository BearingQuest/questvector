# Terminal demo shown in README.md, recorded with VHS (https://github.com/charmbracelet/vhs).
# Re-record from the repository root after a CLI change:  vhs docs/readme/demo.tape
# Uses the synthetic dossier in tests/fixtures/live_narrative (every name, number and
# fact in it is made up) in a throwaway folder. No network, no vault, no keys, and
# nothing from ~/career-workspace. Needs uv sync run once in the clone.

Output docs/readme/demo.gif

Require uv

Set Shell "bash"
Set FontSize 18
Set Width 1280
Set Height 420
Set Padding 24
Set TypingSpeed 40ms
Set Theme { "name": "Bearing Quest Night", "background": "#10213A", "foreground": "#F4F6F8", "cursor": "#E8894F", "selection": "#2E4A72", "black": "#10213A", "red": "#FF8A80", "green": "#8FD19E", "yellow": "#F2C46B", "blue": "#7DB8F0", "magenta": "#E3A1D6", "cyan": "#7FD6E8", "white": "#C9D3DF", "brightBlack": "#8EA0B5", "brightRed": "#FFB4AB", "brightGreen": "#B5E3C0", "brightYellow": "#F7D99A", "brightBlue": "#A9D0F5", "brightMagenta": "#EFC4E8", "brightCyan": "#A8E6F2", "brightWhite": "#FFFFFF" }

Hide
Type `export PS1='$ ' && VIRTUAL_ENV_DISABLE_PROMPT=1 source .venv/bin/activate && QV_DEMO="$(mktemp -d)/workspace" && qv launch --dir "$QV_DEMO" >/dev/null && cp tests/fixtures/live_narrative/Capabilities.md tests/fixtures/live_narrative/Chronology.md tests/fixtures/live_narrative/Impact.md "$QV_DEMO"/ && cp tests/fixtures/live_narrative/job_description.txt "$QV_DEMO"/jd.txt && cd "$QV_DEMO" && clear`
Enter
Sleep 4s
Show

Type `ls`
Sleep 300ms
Enter
Sleep 1.5s

Type `qv sync-ast --dir . --target jd.txt --template devops-senior-mgr`
Sleep 300ms
Enter
Sleep 5s
