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

        stage('Report deployment started') {
            steps { sh 'sh integrations/report-deployment.sh started || echo "Deployment event delivery unconfirmed"' }
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

                            RELEASE_ID="$(git rev-parse --verify HEAD)-${BUILD_NUMBER}"
                            docker tag cloudlaunch-app "cloudlaunch-app:$RELEASE_ID"
                            if [ "${CLOUDLAUNCH_TRIVY_ENABLED:-false}" = true ]; then
                                IMAGE_ID=$(docker image inspect cloudlaunch-app --format='{{.Id}}')
                                trivy image --scanners vuln --exit-code 1 --severity HIGH,CRITICAL \
                                  --format json --output trivy-report.json "$IMAGE_ID"
                            fi
                            export APP_VERSION="$RELEASE_ID"
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

                        sh 'sh integrations/report-deployment.sh succeeded || echo "Deployment event delivery unconfirmed"'
                        echo 'Pharmacy deployment successful.'
                    } catch (err) {
                        sh '''
                            set -eu
                            sh integrations/report-deployment.sh failed || echo 'Deployment event delivery unconfirmed'
                            if [ "${CLOUDLAUNCH_ALLOW_ROLLBACK:-false}" = true ] && \
                              docker image inspect cloudlaunch-app:rollback >/dev/null 2>&1; then
                                sh integrations/report-deployment.sh rollback_started || true
                                docker tag cloudlaunch-app:rollback cloudlaunch-app
                                docker compose --env-file /home/ubuntu/cloudlaunch/.env \
                                  -p cloudlaunch -f compose.yml up -d --no-build --no-deps app
                                rollback_ok=false
                                for i in $(seq 1 45); do
                                    status=$(docker inspect --format='{{.State.Health.Status}}' pharmacy-app 2>/dev/null || echo missing)
                                    current_image=$(docker inspect --format='{{.Image}}' pharmacy-app 2>/dev/null || echo missing)
                                    expected_image=$(docker image inspect cloudlaunch-app:rollback --format='{{.Id}}')
                                    if [ "$status" = healthy ] && [ "$current_image" = "$expected_image" ]; then rollback_ok=true; break; fi
                                    [ "$status" = unhealthy ] && break
                                    sleep 2
                                done
                                if [ "$rollback_ok" = true ]; then
                                    sh integrations/report-deployment.sh rollback_succeeded || true
                                else
                                    sh integrations/report-deployment.sh rollback_failed || true
                                fi
                            else
                                echo 'Automatic rollback disabled or no retained rollback image; review the failed deployment.'
                            fi
                        '''
                        error("Deployment failed. Review rollback policy, deployment events and pharmacy-app logs. ${err}")
                    }
                }
            }
        }
    }
    post {
        failure {
            sh 'sh integrations/report-deployment.sh failed || echo "Deployment event delivery unconfirmed"'
        }
    }
}
