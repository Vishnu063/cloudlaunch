pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
    }

    stages {
        stage('Validate') {
            steps {
                sh '''
                    set -eu
                    test -s app/backend/main.py
                    test -s app/static/index.html
                    test -s Dockerfile
                    test -s compose.yml
                    docker compose --env-file /home/ubuntu/cloudlaunch/.env \
                      -p cloudlaunch -f compose.yml config -q
                '''
            }
        }

        stage('Deploy Pharmacy App') {
            steps {
                script {
                    try {
                        sh '''
                            set -eu
                            OLD_IMAGE=$(docker inspect --format='{{.Image}}' pharmacy-app)
                            docker tag "$OLD_IMAGE" cloudlaunch-app:rollback

                            docker compose --env-file /home/ubuntu/cloudlaunch/.env \
                              -p cloudlaunch -f compose.yml build app

                            docker compose --env-file /home/ubuntu/cloudlaunch/.env \
                              -p cloudlaunch -f compose.yml up -d --no-deps app
                        '''

                        int result = sh(
                            script: '''
                                for i in $(seq 1 45); do
                                    status=$(docker inspect \
                                      --format='{{.State.Health.Status}}' pharmacy-app 2>/dev/null || echo missing)
                                    [ "$status" = "healthy" ] && exit 0
                                    [ "$status" = "unhealthy" ] && exit 1
                                    sleep 2
                                done
                                exit 1
                            ''',
                            returnStatus: true
                        )

                        if (result != 0) {
                            error('Pharmacy health check failed')
                        }

                        echo 'Pharmacy deployment successful.'
                    } catch (err) {
                        sh '''
                            if docker image inspect cloudlaunch-app:rollback >/dev/null 2>&1; then
                                docker tag cloudlaunch-app:rollback cloudlaunch-app
                                docker compose --env-file /home/ubuntu/cloudlaunch/.env \
                                  -p cloudlaunch -f compose.yml up -d --no-build --no-deps app
                            fi
                        '''
                        error("Deployment failed; rollback attempted. Check pharmacy-app logs. ${err}")
                    }
                }
            }
        }
    }
}
