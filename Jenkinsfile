pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps {
                git branch: 'main',
                    url: 'https://github.com/Vishnu063/cloudlaunch.git'
            }
        }

        stage('Validate Website') {
            steps {
                sh 'test -s site/index.html'
                echo 'Website validation passed'
            }
        }

        stage('Deploy') {
            steps {
                sh '''
                    cp site/index.html /tmp/cloudlaunch-index.html
                    sudo docker cp /tmp/cloudlaunch-index.html cloudlaunch:/usr/share/nginx/html/index.html
                    rm -f /tmp/cloudlaunch-index.html
                '''
            }
        }
    }
}
