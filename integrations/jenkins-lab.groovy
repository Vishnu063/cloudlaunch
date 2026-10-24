// For a fresh disposable loopback Jenkins home only; never install on an existing controller.
import jenkins.model.Jenkins
import hudson.model.FreeStyleProject
import hudson.tasks.Shell
import hudson.security.HudsonPrivateSecurityRealm
import hudson.security.FullControlOnceLoggedInAuthorizationStrategy
import hudson.model.Cause

def instance = Jenkins.get()
if (instance.isUseSecurity() || !instance.getAllItems().isEmpty()) {
    throw new IllegalStateException('Refusing to replace an existing controller security realm or jobs')
}
def realm = new HudsonPrivateSecurityRealm(false)
realm.createAccount('lab-owner', new File(System.getenv('JENKINS_LAB_PASSWORD_FILE')).text.trim())
instance.setSecurityRealm(realm)
def authorization = new FullControlOnceLoggedInAuthorizationStrategy()
authorization.setAllowAnonymousRead(false)
instance.setAuthorizationStrategy(authorization)
instance.setNumExecutors(1)
instance.setSystemMessage('Disposable ecosystem acceptance only. Loopback, one executor, no production credentials.')
def job = instance.getItem('ecosystem-disposable') ?: instance.createProject(FreeStyleProject, 'ecosystem-disposable')
job.getBuildersList().clear()
job.getBuildersList().add(new Shell('''#!/bin/sh
set -eu
"$ECOSYSTEM_ROOT/ecosystem-venv/bin/python" "$ECOSYSTEM_ROOT/devops-troubleshooting-labs/integrations/ecosystem_lab.py" \
  --workspace "$ECOSYSTEM_ROOT" --tools "$MONITORING_TOOLS" \
  --output "$WORKSPACE/ecosystem-evidence" --allow-disposable-failure
'''))
job.save()
instance.save()
if (System.getenv('ECOSYSTEM_RUN_LAB') == 'true') { job.scheduleBuild2(0, new Cause.UserIdCause()) }
