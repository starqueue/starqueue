SERVERADDRESS=192.168.1.131

# should return 400 base request
curl -d '{"key1":"value1", "key2":"value2"}' -H "Content-Type: application/json" -X POST http://${SERVERADDRESS}:8000/data/12312


curl -d "param1=value1&param2=value2" -H "Content-Type: application/x-www-form-urlencoded" -X POST http://${SERVERADDRESS}:8000/data/12312