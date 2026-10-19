import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWalletOutlined';
import CategoryIcon from '@mui/icons-material/CategoryOutlined';
import DescriptionIcon from '@mui/icons-material/DescriptionOutlined';
import FactoryIcon from '@mui/icons-material/PrecisionManufacturingOutlined';
import HandshakeIcon from '@mui/icons-material/HandshakeOutlined';
import Inventory2Icon from '@mui/icons-material/Inventory2Outlined';
import LocalShippingIcon from '@mui/icons-material/LocalShippingOutlined';
import PeopleIcon from '@mui/icons-material/PeopleAltOutlined';
import ReceiptIcon from '@mui/icons-material/ReceiptLongOutlined';
import RequestQuoteIcon from '@mui/icons-material/RequestQuoteOutlined';
import ShoppingCartIcon from '@mui/icons-material/ShoppingCartOutlined';
import StraightenIcon from '@mui/icons-material/StraightenOutlined';
import SummarizeIcon from '@mui/icons-material/AccountTreeOutlined';
import TuneIcon from '@mui/icons-material/TuneOutlined';
import WarehouseIcon from '@mui/icons-material/WarehouseOutlined';

const STORE = 'CS Store', PROD = 'CS Production', SALES = 'CS Sales';

/** roles omitted = everyone; admins always see everything. Route guards use the same list. */
export const MENU = [
  {
    section: 'Master',
    items: [
      { label: 'UOM', path: '/uom', icon: StraightenIcon },
      { label: 'Product', path: '/product', icon: Inventory2Icon },
      { label: 'Category', path: '/category', icon: CategoryIcon },
      { label: 'Process', path: '/process', icon: TuneIcon, roles: [STORE, PROD] },
      { label: 'Purchase', path: '/purchase', icon: ShoppingCartIcon, roles: [STORE] },
      { label: 'Batch', path: '/batch', icon: FactoryIcon, roles: [PROD] },
      { label: 'Quotation', path: '/quotation', icon: RequestQuoteIcon, roles: [SALES] },
      { label: 'Sales Order', path: '/sales-order', icon: ReceiptIcon, roles: [SALES, STORE] },
    ],
  },
  {
    section: 'Supporting',
    items: [
      { label: 'Vendor', path: '/vendor', icon: HandshakeIcon, roles: [STORE, PROD] },
      { label: 'Customer', path: '/customer', icon: PeopleIcon, roles: [SALES, STORE] },
      { label: 'Outstanding', path: '/customer-outstanding', icon: AccountBalanceWalletIcon, roles: [SALES, STORE] },
      { label: 'Charge', path: '/charge', icon: DescriptionIcon, roles: [PROD] },
      { label: 'Inventory', path: '/inventory', icon: WarehouseIcon, roles: [STORE, PROD] },
      { label: 'Dispatch', path: '/dispatch', icon: LocalShippingIcon, roles: [STORE, SALES] },
    ],
  },
];

