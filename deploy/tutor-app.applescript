-- Tutor Server control app — built by deploy/make-tutor-app.sh.
-- Double-click → choose an action. Requires the backend venv + .env
-- to be set up (README.md).
on run
	set scriptPath to "PROJECT_DIR_PLACEHOLDER/deploy/tutor-server.sh"
	set dashboardUrl to "http://localhost:8000"
	set actions to {"Start server", "Stop server", "Restart server", "Status", "Open dashboard", "View logs", "Quit"}
	repeat
		set choice to choose from list actions with title "Tutor Server" with prompt "Speak, Don't Just Read — what do you want to do?" default items {"Start server"} cancel button name "Quit"
		if choice is false then exit repeat
		set action to item 1 of choice
		if action is "Quit" then exit repeat
		set cmd to quoted form of scriptPath & " " & quoted form of (my argFor(action))
		set output to do shell script cmd
		if action is "Start server" or action is "Restart server" then
			display dialog output buttons {"Close", "Open dashboard"} default button "Open dashboard" with title "Tutor Server"
			if button returned of result is "Open dashboard" then do shell script "open " & quoted form of dashboardUrl
		else
			display dialog output buttons {"OK"} default button "OK" with title "Tutor Server"
		end if
	end repeat
end run

on argFor(a)
	if a is "Start server" then return "start"
	if a is "Stop server" then return "stop"
	if a is "Restart server" then return "restart"
	if a is "Status" then return "status"
	if a is "Open dashboard" then return "open"
	if a is "View logs" then return "logs"
	return ""
end argFor
