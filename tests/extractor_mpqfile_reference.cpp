/* Exercise each actual patched MPQFile constructor using synthetic data only. */
#include "mpq_libmpq04.h"
#include "EsteriaArchiveOrder.h"
int main(int argc,char** argv) {
    try {
        int status=EsteriaOrder::Bootstrap(argc,argv);if(status>=0)return status;
        EsteriaOrder::Need(EsteriaOrder::Active() && !EsteriaOrder::MemberProbe().empty(),"explicit member probe required");
        MPQFile file(EsteriaOrder::MemberProbe().c_str());bool found=!file.isEof();
        return EsteriaOrder::EmitProbe(found?file.getBuffer():nullptr,found?file.getSize():0,found);
    } catch(std::exception const& error) {std::fprintf(stderr,"ordered MPQFile refused: %s\n",error.what());return 2;}
}
