// This autogenerated skeleton file illustrates how to build a server.
// You should copy it to another filename to avoid overwriting it.

#include "ESDB.h"
#include <protocol/TBinaryProtocol.h>
#include <server/TSimpleServer.h>
#include <transport/TServerSocket.h>
#include <transport/TTransportUtils.h>

using namespace facebook::thrift;
using namespace facebook::thrift::protocol;
using namespace facebook::thrift::transport;
using namespace facebook::thrift::server;

using boost::shared_ptr;

using namespace ESSNMP;

class ESDBHandler : virtual public ESDBIf {
 public:
  ESDBHandler() {
    // Your initialization goes here
  }

  void list_devices(std::vector<std::string> & _return) {
    // Your implementation goes here
    printf("list_devices\n");
  }

  void get_device(Device& _return, const std::string& name) {
    // Your implementation goes here
    printf("get_device\n");
  }

  void get_all_devices(std::map<std::string, Device> & _return) {
    // Your implementation goes here
    printf("get_all_devices\n");
  }

  void add_device(const std::string& name, const std::string& begin_time, const std::string& end_time) {
    // Your implementation goes here
    printf("add_device\n");
  }

  void update_device(const std::string& name, const std::string& begin_time, const std::string& end_time) {
    // Your implementation goes here
    printf("update_device\n");
  }

  void list_device_oidsets(std::vector<OIDSet> & _return, const Device& device) {
    // Your implementation goes here
    printf("list_device_oidsets\n");
  }

  void list_oids(std::vector<std::string> & _return) {
    // Your implementation goes here
    printf("list_oids\n");
  }

  void get_oid(OID& _return, const std::string& name) {
    // Your implementation goes here
    printf("get_oid\n");
  }

  void add_oid(const std::string& name, const std::string& storage, const std::string& oidtype) {
    // Your implementation goes here
    printf("add_oid\n");
  }

  void list_oidsets(std::vector<std::string> & _return) {
    // Your implementation goes here
    printf("list_oidsets\n");
  }

  void get_oidset(OIDSet& _return, const std::string& name) {
    // Your implementation goes here
    printf("get_oidset\n");
  }

  void get_oidset_devices(std::vector<Device> & _return, const OIDSet& oidset) {
    // Your implementation goes here
    printf("get_oidset_devices\n");
  }

  void get_vars_by_grouping(VarList& _return, const Grouping grouping) {
    // Your implementation goes here
    printf("get_vars_by_grouping\n");
  }

  int8_t store_poll_result(const SNMPPollResult& result) {
    // Your implementation goes here
    printf("store_poll_result\n");
  }

  void select(VarList& _return, const std::string& device, const std::string& iface_name, const std::string& oidset, const std::string& oid, const std::string& begin_time, const std::string& end_time, const std::string& flags, const std::string& cf, const std::string& resolution) {
    // Your implementation goes here
    printf("select\n");
  }

};

int main(int argc, char **argv) {
  int port = 9090;
  shared_ptr<ESDBHandler> handler(new ESDBHandler());
  shared_ptr<TProcessor> processor(new ESDBProcessor(handler));
  shared_ptr<TServerTransport> serverTransport(new TServerSocket(port));
  shared_ptr<TTransportFactory> transportFactory(new TBufferedTransportFactory());
  shared_ptr<TProtocolFactory> protocolFactory(new TBinaryProtocolFactory());

  TSimpleServer server(processor, serverTransport, transportFactory, protocolFactory);
  server.serve();
  return 0;
}

