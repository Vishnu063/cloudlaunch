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
                    test -s tests/conftest.py
                    test -s tests/test_stock.py

                    docker compose --env-file /home/ubuntu/cloudlaunch/.env \
                      -p cloudlaunch -f compose.yml config -q
                '''
            }
        }

        stage('Automated Tests') {
            steps {
                sh '''
                    set -eu
                    set +x

                    POSTGRES_PASSWORD=$(grep '^POSTGRES_PASSWORD=' \
                      /home/ubuntu/cloudlaunch/.env | cut -d= -f2-)
                    test -n "$POSTGRES_PASSWORD"

                    docker run --rm \
                      --network cloudlaunch_pharmacy_internal \
                      --env-file /home/ubuntu/cloudlaunch/.env \
                      -e "DATABASE_URL=postgresql+psycopg://pharmacy_user:${POSTGRES_PASSWORD}@db:5432/pharmacy_test" \
                      -e PYTHONPATH=/src \
                      -v "$WORKSPACE:/src:ro" \
                      -w /src \
                      cloudlaunch-app \
                      sh -c 'pip install -q pytest httpx && python -m pytest -q -p no:cacheprovider tests'
                '''
            }
        }

        stage('Optional Trivy security gate') {
            when { expression { env.CLOUDLAUNCH_TRIVY == '1' } }
            steps {
                sh '''
                    set -eu
                    command -v trivy >/dev/null
                    trivy fs --timeout 2m --exit-code 1 --severity HIGH,CRITICAL --scanners vuln --no-progress .
                '''
            }
            post {
                failure {
                    script {
                        sh(script: 'python3 scripts/report-release.py security_failed', returnStatus: true)
                    }
                }
            }
        }

        stage('Deploy Pharmacy App') {
            steps {
                script {
                    try {
                        sh(script: 'python3 scripts/report-release.py started', returnStatus: true)
                        sh '''
                            set -eu
                            OLD_IMAGE=$(docker inspect --format='{{.Image}}' pharmacy-app)
                            docker tag "$OLD_IMAGE" cloudlaunch-app:rollback

                            docker compose --env-file /home/ubuntu/cloudlaunch/.env \
                              -p cloudlaunch -f compose.yml build app

                            if [ "${CLOUDLAUNCH_TRIVY:-0}" = "1" ]; then
                                trivy image --timeout 2m --exit-code 1 --severity HIGH,CRITICAL --no-progress cloudlaunch-app
                            fi
                            RELEASE_ID=$(git rev-parse HEAD)
                            docker tag cloudlaunch-app "cloudlaunch-app:${RELEASE_ID}"

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

                        sh(script: 'python3 scripts/report-release.py healthy', returnStatus: true)
                        echo 'Pharmacy deployment successful.'
                    } catch (err) {
                        sh(script: 'python3 scripts/report-release.py failed', returnStatus: true)
                        sh(script: 'python3 scripts/report-release.py rollback_started', returnStatus: true)
                        int rollbackResult = sh(script: '''
                            set -eu
                            docker image inspect cloudlaunch-app:rollback >/dev/null
                            docker tag cloudlaunch-app:rollback cloudlaunch-app
                            docker compose --env-file /home/ubuntu/cloudlaunch/.env \
                              -p cloudlaunch -f compose.yml up -d --no-build --no-deps app
                            for i in $(seq 1 45); do
                                status=$(docker inspect --format='{{.State.Health.Status}}' pharmacy-app 2>/dev/null || echo missing)
                                [ "$status" = "healthy" ] && exit 0
                                [ "$status" = "unhealthy" ] && exit 1
                                sleep 2
                            done
                            exit 1
                        ''', returnStatus: true)
                        sh(script: 'python3 scripts/report-release.py ' + (rollbackResult == 0 ? 'rollback_verified' : 'rollback_failed'), returnStatus: true)
                        error("Deployment failed; rollback attempted. Check pharmacy-app logs. ${err}")
                    }
                }
            }
        }
    }
}

